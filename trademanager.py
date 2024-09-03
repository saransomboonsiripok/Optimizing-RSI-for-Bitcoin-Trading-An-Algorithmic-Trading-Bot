from threading import Thread

from binance import ThreadedWebsocketManager
from binance.client import Client
from binance.enums import SIDE_SELL, SIDE_BUY, FUTURE_ORDER_TYPE_MARKET, FUTURE_ORDER_TYPE_LIMIT, TIME_IN_FORCE_GTC, \
    FUTURE_ORDER_TYPE_STOP_MARKET, FUTURE_ORDER_TYPE_TAKE_PROFIT
from binance.exceptions import BinanceAPIException
from tabulate import tabulate

import strategy
from configuration import *
import time
from helper import Trade
from logger import *


class TradeManager:
    def __init__(self, client: Client, new_trades_q, print_trades_q):
        self.client = client
        self.active_trades: [Trade] = []
        self.use_trailing_stop = False
        self.use_market_orders = True
        self.new_trades_q = new_trades_q
        self.twm = ThreadedWebsocketManager(api_key=API_KEY, api_secret=API_SECRET, testnet= True)
        self.twm.start()
        self.user_socket = self.twm.start_futures_user_socket(callback=self.monitor_trades)
        self.print_trades_q = print_trades_q
        self.log_trades_loop_thread = Thread(target=self.log_trades_loop)
        self.log_trades_loop_thread.daemon = True
        self.log_trades_loop_thread.start()
        self.monitor_orders_by_polling_api_loop = Thread(target=self.monitor_orders_by_polling_api)
        self.monitor_orders_by_polling_api_loop.daemon = True
        self.monitor_orders_by_polling_api_loop.start()
        self.total_profit = 0
        self.number_of_wins = 0
        self.number_of_losses = 0

    def monitor_orders_by_polling_api(self):
        '''
        Loop that runs constantly to catch trades that opened when packet loss occurs
        to ensure that SL & TPs are placed on all positions
        '''
        while True:
            time.sleep(15)
            open_positions = self.get_all_open_positions()
            if open_positions == []:
                continue
            try:
                for trade in self.active_trades:
                    if trade.symbol in open_positions and trade.trade_status == 0:
                        i = self.active_trades.index(trade)
                        trade.trade_status = self.place_tp_sl(trade.symbol, trade.trade_direction, trade.CP, trade.tick_size, trade.entry_price, i)
            except Exception as e:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                log.warning(f'monitor_orders_by_polling_api() - error occurred, Error Info: {exc_obj, fname, exc_tb.tb_lineno}, Error: {e}')

    def new_trades_loop(self):
        ''' Loop that constantly runs and opens new trades as they come in '''
        while True:
            [symbol, OP, CP, tick_size, trade_direction, index, stop_loss_val, take_profit_val] = self.new_trades_q.get()
            open_trades = self.get_all_open_or_pending_trades()
            if open_trades != -1 and symbol not in open_trades:
                try:
                    order_id, order_qty, entry_price, trade_status = self.open_trade(symbol, trade_direction, OP, tick_size, stop_loss_val, CP)
                    if trade_status != -1:
                        self.active_trades.append(Trade(index, entry_price, order_qty, take_profit_val, stop_loss_val, trade_direction, order_id, symbol, CP, tick_size))
                    elif trade_status == 0:
                        log.info(f'new_trades_loop() - Order placed on {symbol}, Entry price: {entry_price}, order quantity: {order_qty}, Side: {"Long" if trade_direction else "Short"}')

                except Exception as e:
                    exc_type, exc_obj, exc_tb = sys.exc_info()
                    fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                    log.warning(f'new_trades_loop() - error occurred, Error Info: {exc_obj, fname, exc_tb.tb_lineno}, Error: {e}')

    def monitor_trades(self, msg):
        try:
            trades_to_update = []
            # for i in range(len(self.active_trades)):
            for trade in self.active_trades:
                if msg['e'] == 'ORDER_TRADE_UPDATE' and msg['o']['s'] == trade.symbol and msg['o']['X'] == 'FILLED':
                    i = self.active_trades.index(trade)
                    if float(msg['o']['rp']) > 0 and msg['o']['i'] == trade.TP_id:
                        self.total_profit += float(msg['o']['rp'])
                        self.number_of_wins += 1
                        trades_to_update.append([i, 4])
                    elif float(msg['o']['rp']) < 0 and msg['o']['i'] == trade.SL_id:
                        self.total_profit += float(msg['o']['rp'])
                        self.number_of_losses += 1
                        trades_to_update.append([i, 5])
                    elif msg['o']['i'] == trade.order_id:
                        status = self.place_tp_sl(trade.symbol, trade.trade_direction, trade.CP, trade.tick_size, trade.entry_price, i)
                        trades_to_update.append([i, status])
                elif msg['e'] == 'ACCOUNT_UPDATE':
                    i = self.active_trades.index(trade)
                    for position in msg['a']['P']:
                        if position['s'] == trade.symbol and position['pa'] == '0':
                            trades_to_update.append([i, 6])
            for [index, status] in trades_to_update:
                self.active_trades[index].trade_status = status
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            log.warning(f'monitor_trades() - error occurred, Error Info: {exc_obj, fname, exc_tb.tb_lineno}, Error: {e}')

    def place_tp_sl(self, symbol, trade_direction, CP, tick_size, entry_price, index):
        ''' Opens TP and SL positions '''
        try:
            ## Cancel any open orders to get around an issue with partially filled orders
            self.client.futures_coin_cancel_all_open_orders(symbol=symbol)
        except:
            pass
        self.active_trades[index].position_size = abs([float(position['positionAmt']) for position in self.client.futures_position_information() if position['symbol'] == symbol][0])
        self.active_trades[index].SL_id = self.place_SL(symbol, self.active_trades[index].SL_val, trade_direction, CP, tick_size, self.active_trades[index].position_size)
        self.active_trades[index].TP_id = self.place_TP(symbol, [self.active_trades[index].TP_val, self.active_trades[index].position_size], trade_direction, CP, tick_size)
        if self.active_trades[index].SL_id != -1 and self.active_trades[index].TP_id != -1:
            log.info(f'new_trades_loop() - Position opened on {symbol}, orderId: {self.active_trades[-1].order_id}, Entry price: {entry_price}, order quantity: {self.active_trades[index].position_size}, Side: {"Long" if trade_direction else "Short"}\n'
                     f' Take Profit & Stop loss have been placed')
            self.print_trades_q.put(True)
            return 1
        else:
            return 3  ## Signals to close the trade as it doesn't have either a Take Profit or a Stop Loss

    def get_all_open_or_pending_trades(self):
        ''' Gets all opened trades, User opened positions + Bot opened trades + Pending Bot trades '''
        try:
            open_trades_symbols = [position['symbol'] for position in self.client.futures_position_information() if float(position['notional']) != 0.0]  ## All open Trades
            active_trade_symbols = [trade.symbol for trade in self.active_trades]
            return open_trades_symbols + active_trade_symbols
        except Exception as e:
            log.warning(f'get_all_open_or_pending_trades() - Error occurred: {e}')
            return -1

    def get_all_open_positions(self):
        ''' Gets all open positions from binance '''
        try:
            return [position['symbol'] for position in self.client.futures_position_information() if float(position['notional']) != 0.0] ## TODO convert this to a hashmap perhaps {symbol: position_size,...}
        except Exception as e:
            log.warning(f'get_all_open_trades() - Error occurred: {e}')
            return []


    def cancel_and_remove_trades(self):
        ''' Function that removes finished trades from the active_trades list '''
        i = 0
        open_trades = self.get_all_open_positions()
        while i < len(self.active_trades):
            if self.active_trades[i].trade_status == 2 and open_trades != []:
                try:
                    pop_trade = self.check_position_and_cancel_orders(self.active_trades[i], open_trades)
                    if pop_trade:
                        log.info(f'cancel_and_remove_trades() - orders cancelled on {self.active_trades[i].symbol} as price surpassed the trading threshold set in live_trading_config.py\n '
                                 f'Current Price was: {self.active_trades[i].current_price}, Attempted entry price was: {self.active_trades[i].entry_price}, % moved: {abs(100*(self.active_trades[i].entry_price-self.active_trades[i].current_price)/self.active_trades[i].entry_price)}')
                        self.active_trades.pop(i)
                    else:
                        self.active_trades[i].trade_status = 0
                        i += 1
                except Exception as e:
                    exc_type, exc_obj, exc_tb = sys.exc_info()
                    fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                    log.warning(f'cancel_and_remove_trades() - error occurred cancelling a trade on {self.active_trades[i].symbol}, Error Info: {exc_obj, fname, exc_tb.tb_lineno}, Error: {e}')
            elif self.active_trades[i].trade_status == 3:
                try:
                    self.close_position(self.active_trades[i].symbol, self.active_trades[i].trade_direction, self.active_trades[i].position_size)
                    if self.active_trades[i].SL_id == -1:
                        log.info(f'cancel_and_remove_trades() - orders cancelled on {self.active_trades[i].symbol} as there was an issue placing the Stop loss')
                    else:
                        log.info(f'cancel_and_remove_trades() - orders cancelled on {self.active_trades[i].symbol} as there was an issue placing the Take Profit')
                    self.active_trades.pop(i)
                except Exception as e:
                    exc_type, exc_obj, exc_tb = sys.exc_info()
                    fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                    log.warning(f'cancel_and_remove_trades() - error occurred cancelling a trade on {self.active_trades[i].symbol}, Error Info: {exc_obj, fname, exc_tb.tb_lineno}, Error: {e}')
            elif self.active_trades[i].trade_status == 4:
                try:
                    self.client.futures_cancel_all_open_orders(symbol=self.active_trades[i].symbol)
                    log.info(f'cancel_and_remove_trades() - orders cancelled on {self.active_trades[i].symbol} as Take Profit was hit')
                    self.active_trades.pop(i)
                except Exception as e:
                    exc_type, exc_obj, exc_tb = sys.exc_info()
                    fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                    log.warning(f'cancel_and_remove_trades() - error occurred closing open orders on {self.active_trades[i].symbol}, Error Info: {exc_obj, fname, exc_tb.tb_lineno}, Error: {e}')
            elif self.active_trades[i].trade_status == 5:
                try:
                    self.client.futures_cancel_all_open_orders(symbol=self.active_trades[i].symbol)
                    log.info(f'cancel_and_remove_trades() - orders cancelled on {self.active_trades[i].symbol} as Stop loss was hit')
                    self.active_trades.pop(i)
                except Exception as e:
                    exc_type, exc_obj, exc_tb = sys.exc_info()
                    fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                    log.warning(f'cancel_and_remove_trades() - error occurred closing open orders on {self.active_trades[i].symbol}, Error Info: {exc_obj, fname, exc_tb.tb_lineno}, Error: {e}')
            elif self.active_trades[i].trade_status == 6:
                try:
                    self.client.futures_cancel_all_open_orders(symbol=self.active_trades[i].symbol)
                    log.info(f'cancel_and_remove_trades() - orders cancelled on {self.active_trades[i].symbol} as trade was closed, possibly by the user')
                    self.active_trades.pop(i)
                except Exception as e:
                    exc_type, exc_obj, exc_tb = sys.exc_info()
                    fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                    log.warning(f'cancel_and_remove_trades() - error occurred cancelling a trade on {self.active_trades[i].symbol}, Error Info: {exc_obj, fname, exc_tb.tb_lineno}, Error: {e}')
            else:
                i += 1

    def open_trade(self, symbol, trade_direction, OP, tick_size, stop_loss_val, CP):
        ''' Function to open a new trade '''
        ticker = self.client.futures_symbol_ticker(symbol = symbol)
        current_price = float(ticker['price'])
        account_balance_info = self.client.futures_account_balance()
        account_balance = 0
        for balance in account_balance_info:
            if balance['asset'] == 'USDT':
                account_balance = balance['balance']

        order_notional = account_balance / 2
        order_qty = order_notional / current_price
        market_entry_price = 0
        market_order_id = ''

        if OP == 0:
            order_qty = round(order_qty)
        else:
            order_qty = round(order_qty, OP)

        # first order
        try:
            if trade_direction == 0:
                order = self.client.futures_create_order(
                    symbol=symbol,
                    side=SIDE_SELL,
                    type=FUTURE_ORDER_TYPE_MARKET,
                    quantity=order_qty)
                market_order_id = order['orderId']
            if trade_direction == 1:
                order = self.client.futures_create_order(
                    symbol=symbol,
                    side=SIDE_BUY,
                    type=FUTURE_ORDER_TYPE_MARKET,
                    quantity=order_qty)
                market_order_id = order['orderId']

            market_entry_price = float(self.client.futures_position_information(symbol=symbol)[0]['entryPrice'])

            # average down
            try:
                account_balance_info = self.client.futures_account_balance()
                account_balance = 0
                for balance in account_balance_info:
                    if balance['asset'] == 'USDT':
                        account_balance = balance['balance']
                order_notional = account_balance
                if trade_direction == 1:
                    avg_down_price = (market_entry_price - (SL_mult * stop_loss_val))
                    avg_down_qty = order_notional / avg_down_price
                    order = self.client.futures_create_order(
                        symbol=symbol,
                        side=SIDE_BUY,
                        type=FUTURE_ORDER_TYPE_LIMIT,
                        price=avg_down_price,
                        timeInForce=TIME_IN_FORCE_GTC,
                        quantity=avg_down_qty)
                elif trade_direction == 0:
                    avg_down_price = (market_entry_price + (SL_mult * stop_loss_val))
                    avg_down_qty = order_notional / avg_down_price
                    order = self.client.futures_create_order(
                        symbol=symbol,
                        side=SIDE_SELL,
                        type=FUTURE_ORDER_TYPE_LIMIT,
                        price=avg_down_price,
                        timeInForce=TIME_IN_FORCE_GTC,
                        quantity=avg_down_qty)

            except Exception as e:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                log.warning(
                    f'open_trade() - error occurred placing average down order on {symbol}, OP: {OP}, trade direction: {trade_direction}, '
                    f'Quantity: {order_qty}, Error Info: {exc_obj, fname, exc_tb.tb_lineno}, Error: {e}')

            # stop loss - here stop loss val should be ATR
            try:
                if trade_direction == 1:
                    SL = market_entry_price - (SL_mult * stop_loss_val)
                if trade_direction == 0:
                    SL = market_entry_price + (SL_mult * stop_loss_val)

                if CP == 0:
                    SL = round(SL)
                else:
                    SL = round(round(SL / tick_size) * tick_size, CP)

                if trade_direction == 1:
                    sl_order = self.client.futures_create_order(
                        symbol=symbol,
                        side=SIDE_SELL,
                        type=FUTURE_ORDER_TYPE_STOP_MARKET,
                        stopprice=SL,
                        quantity = order_qty + avg_down_qty,
                        closePosition='true')
                elif trade_direction == 0:
                    sl_order = self.client.futures_create_order(
                        symbol=symbol,
                        side=SIDE_BUY,
                        type=FUTURE_ORDER_TYPE_STOP_MARKET,
                        price=SL,
                        quantity = order_qty + avg_down_qty,
                        closePosition = 'true')

            except Exception as e:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                log.warning(
                    f'open_trade() - error occurred placing stoploss order on {symbol}, OP: {OP}, trade direction: {trade_direction}, '
                    f'Quantity: {order_qty}, Error Info: {exc_obj, fname, exc_tb.tb_lineno}, Error: {e}')

        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            log.warning(
                f'open_trade() - error occurred placing market order on {symbol}, OP: {OP}, trade direction: {trade_direction}, '
                f'Quantity: {order_qty}, Error Info: {exc_obj, fname, exc_tb.tb_lineno}, Error: {e}')
            return -1, -1, -1, -1

        return market_order_id, order_qty, market_entry_price, 1

    def get_account_balance(self):
        ''' Function that returns the USDT balance of the account '''
        try:
            account_balance_info = self.client.futures_account_balance()
            for x in account_balance_info:
                if x['asset'] == 'USDT':
                    return float(x['balance'])
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            log.warning(f'get_account_balance() - error getting account balance, Error Info: {exc_obj, fname, exc_tb.tb_lineno}, Error: {e}')

    def place_TP(self, symbol: str, TP: [float, float], trade_direction: int, CP: int, tick_size: float):
        ''' Function that places a new TP order '''
        TP_ID = ''
        TP_val = 0
        try:
            order = ''
            order_side = ''
            if CP == 0:
                TP_val = round(TP[0])
            else:
                TP_val = round(round(TP[0] / tick_size) * tick_size, CP)
            if trade_direction == 1:
                order_side = SIDE_SELL
            elif trade_direction == 0:
                order_side = SIDE_BUY
            order = self.client.futures_create_order(
                symbol=symbol,
                side=order_side,
                type=FUTURE_ORDER_TYPE_TAKE_PROFIT,
                price=TP_val,
                stopPrice=TP_val,
                timeInForce=TIME_IN_FORCE_GTC,
                reduceOnly='true',
                quantity=TP[1])
            TP_ID = order['orderId']
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            log.warning(f"place_TP() - Error occurred placing TP on {symbol}, price: {TP_val}, amount: {TP[1]}, Error: {e}, {exc_type, fname, exc_tb.tb_lineno}")
            return -1

        return TP_ID

    def place_SL(self, symbol: str, SL: float, trade_direction: int, CP: int, tick_size: float, quantity: float):
        ''' Function that places a new SL order '''
        order_ID = ''
        try:
            if CP == 0:
                SL = round(SL)
            else:
                SL = round(round(SL / tick_size) * tick_size, CP)
            order_side = ''
            if trade_direction == 1:
                order_side = SIDE_SELL
            elif trade_direction == 0:
                order_side = SIDE_BUY

            order = self.client.futures_create_order(
                symbol=symbol,
                side=order_side,
                type=FUTURE_ORDER_TYPE_STOP_MARKET,
                reduceOnly='true',
                stopPrice=SL,
                quantity=quantity)
            order_ID = order['orderId']
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            log.warning(f"place_SL() - Error occurred placing SL on {symbol}, price: {SL}, Error: {e}, {exc_type, fname, exc_tb.tb_lineno}")
            return -1

        return order_ID

    def close_position(self, symbol: str, trade_direction: int, total_position_size: float):
        '''
        Function for closing an open position, used when something goes wrong with a trade
        Can also be used to close a position based off a condition met in your strategy
        '''
        try:
            self.client.futures_cancel_all_open_orders(symbol=symbol)  ##cancel orders for this symbol
        except:
            log.warning(f'close_position() issue cancelling open orders on {symbol} potentially there were no open orders')
        if trade_direction == 0:
            self.client.futures_create_order(
                symbol=symbol,
                side=SIDE_BUY,
                type=FUTURE_ORDER_TYPE_MARKET,
                quantity=total_position_size)
        if trade_direction == 1:
            self.client.futures_create_order(
                symbol=symbol,
                side=SIDE_SELL,
                type=FUTURE_ORDER_TYPE_MARKET,
                quantity=total_position_size)

    def check_position_and_cancel_orders(self, trade: Trade, open_trades: [str]):
        ''' Function that checks we haven't entered a position before cancelling it '''
        if trade.symbol not in open_trades:
            self.client.futures_cancel_all_open_orders(symbol=trade.symbol)
            return True
        else:
            return False

    def log_trades_loop(self):
        ''' Loop that runs constantly and updates the logs for the user when something happens or when a new candle is received '''
        while True:
            try:
                self.print_trades_q.get()
                position_information = [position for position in self.client.futures_position_information() if float(position['notional']) != 0.0]
                win_loss = 'Not available yet'
                if self.number_of_losses != 0:
                    win_loss = round(self.number_of_wins / self.number_of_losses, 4)
                if len(position_information) != 0:
                    info = {'Symbol': [], 'Position Size': [], 'Direction': [], 'Entry Price': [], 'Market Price': [], 'PNL': []}
                    orders = self.client.futures_get_open_orders()
                    open_orders = {f'{str(order["symbol"]) + "_TP"}': float(order['price']) for order in orders if
                                   order['reduceOnly'] is True and order['type'] == 'TAKE_PROFIT'}
                    open_orders_SL = {f'{str(order["symbol"]) + "_SL"}': float(order['stopPrice']) for order in orders if
                                      order['origType'] == 'STOP_MARKET'}
                    open_orders.update(open_orders_SL)
                    for position in position_information:
                        info['Symbol'].append(position['symbol'])
                        info['Position Size'].append(position['positionAmt'])
                        if float(position['notional']) > 0:
                            info['Direction'].append('LONG')
                        else:
                            info['Direction'].append('SHORT')
                        info['Entry Price'].append(position['entryPrice'])
                        info['Market Price'].append(position['markPrice'])
                        info['PNL'].append(float(position['unRealizedProfit']))
                    log.info(f'Account Balance: ${round(self.get_account_balance(), 3)}, Total profit: ${round(self.total_profit, 3)}, PNL: ${round(sum(info["PNL"]),3)}, Wins: {self.number_of_wins}, Losses: {self.number_of_losses}, Win/Loss ratio: {win_loss}, Open Positions: {len(info["Symbol"])}\n' + tabulate(
                            info, headers='keys', tablefmt='github'))
                else:
                    log.info(f'Account Balance: ${round(self.get_account_balance(), 3)}, Total profit: ${round(self.total_profit, 3)}, Wins: {self.number_of_wins}, Losses: {self.number_of_losses}, Win/Loss ratio: {win_loss},  No Open Positions')
            except Exception as e:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                log.warning(f'log_trades_loop() - Error: {e}, {exc_type, fname, exc_tb.tb_lineno}')



def start_new_trades_loop_multiprocess(client: Client, new_trades_q, print_trades_q):
    TM = TradeManager(client, new_trades_q, print_trades_q)
    TM.new_trades_loop()