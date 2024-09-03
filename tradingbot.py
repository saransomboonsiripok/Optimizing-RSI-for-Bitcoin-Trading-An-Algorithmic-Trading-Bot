from ta.momentum import stochrsi_d, stochrsi_k, stoch, stoch_signal, rsi
from ta.trend import ema_indicator, macd_signal, macd, sma_indicator
from ta.volatility import average_true_range, bollinger_pband
import pandas as pd
import strategy as TS
from logger import *
from configuration import *
from binance.client import Client
from binance.enums import SIDE_SELL, SIDE_BUY, FUTURE_ORDER_TYPE_MARKET, FUTURE_ORDER_TYPE_LIMIT, TIME_IN_FORCE_GTC, \
    FUTURE_ORDER_TYPE_STOP_MARKET, FUTURE_ORDER_TYPE_TAKE_PROFIT

class Bot:
    def __init__(self, symbol: str, Open: [float], Close: [float], High: [float], Low: [float], Volume: [float], Date: [str], OP: int, CP: int, index: int, tick: float,
                 strategy: str, TP_SL_choice: str, SL_mult: float, TP_mult: float, backtesting=0, signal_queue=None, print_trades_q=None):
        self.symbol = symbol
        self.Date = Date

        # Remove extra candle if present
        shortest = min(len(Open), len(Close), len(High), len(Low), len(Volume))
        self.Open = Open[-shortest:]
        self.Close = Close[-shortest:]
        self.High = High[-shortest:]
        self.Low = Low[-shortest:]
        self.Volume = Volume[-shortest:]
        self.client = Client(api_key=API_KEY, api_secret=API_SECRET, testnet=True)

        self.OP = OP
        self.CP = CP
        self.index = index
        self.add_hist_complete = 0
        self.Open_H, self.Close_H, self.High_H, self.Low_H = [], [], [], []
        self.tick_size = tick
        self.socket_failed = False
        self.backtesting = backtesting
        self.use_close_pos = False
        self.strategy = strategy
        self.TP_SL_choice = TP_SL_choice
        self.SL_mult = SL_mult
        self.TP_mult = TP_mult
        self.indicators = {}
        self.current_index = -1  ## -1 for live Bot to always reference the most recent candle, will update in Backtester
        self.take_profit_val, self.stop_loss_val = [], []
        self.peaks, self.troughs = [], []
        self.signal_queue = signal_queue
        if self.index == 0:
            self.print_trades_q = print_trades_q
        if backtesting:
            self.add_hist([], [], [], [], [], [])
            self.update_indicators()
            self.update_TP_SL()
        self.first_interval = False
        self.pop_previous_value = False

    def update_indicators(self):
        ## Calculate indicators
        try:
            match self.strategy:
                case 'RSI':
                    CloseS = pd.Series(self.Close)
                    HighS = pd.Series(self.High)
                    LowS = pd.Series(self.Low)
                    self.indicators = {"SMA": {"values": list(sma_indicator(CloseS, window=100)),
                                                 "plotting_axis": 1},
                                       "RSI": {"values": list(rsi(CloseS, window= RSI_window)),
                                               "plotting_axis": 3},
                                       "ATR": {"values": list(average_true_range(high= HighS, low= LowS, close= CloseS, window= RSI_window))}
                    }
                case _:
                    return
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            log.error(f'update_indicators() - Error occurred with strategy: {self.strategy}, Error Info: {exc_obj, fname, exc_tb.tb_lineno}, Error: {e}')


    def add_hist(self, Date_temp: [float], Open_temp: [float], Close_temp: [float], High_temp: [float], Low_temp: [float], Volume_temp: [str]):
        if not self.backtesting:
            try:
                while 0 < len(self.Date):
                    if self.Date[0] > Date_temp[-1]:
                        Date_temp.append(self.Date.pop(0))
                        Open_temp.append(self.Open.pop(0))
                        Close_temp.append(self.Close.pop(0))
                        High_temp.append(self.High.pop(0))
                        Low_temp.append(self.Low.pop(0))
                        Volume_temp.append(self.Volume.pop(0))
                    else:
                        self.Date.pop(0)
                        self.Open.pop(0)
                        self.Close.pop(0)
                        self.High.pop(0)
                        self.Low.pop(0)
                        self.Volume.pop(0)
                self.Date = Date_temp
                self.Open = Open_temp
                self.Close = Close_temp
                self.High = High_temp
                self.Low = Low_temp
                self.Volume = Volume_temp
            except Exception as e:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                log.error(f'add_hist() - Error occurred joining historical and websocket data, Error Info: {exc_obj, fname, exc_tb.tb_lineno}, Error: {e}')
        try:

            self.Close_H.append((self.Open[0] + self.Close[0] + self.Low[0] + self.High[0]) / 4)
            self.Open_H.append((self.Close[0] + self.Open[0]) / 2)
            self.High_H.append(self.High[0])
            self.Low_H.append(self.Low[0])
            for i in range(1, len(self.Close)):
                self.Open_H.append((self.Open_H[i-1] + self.Close_H[i-1]) / 2)
                self.Close_H.append((self.Open[i] + self.Close[i] + self.Low[i] + self.High[i]) / 4)
                self.High_H.append(max(self.High[i], self.Open_H[i], self.Close_H[i]))
                self.Low_H.append(min(self.Low[i], self.Open_H[i], self.Close_H[i]))
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            log.error(f'add_hist() - Error occurred creating heikin ashi candles, Error Info: {exc_obj, fname, exc_tb.tb_lineno}, Error: {e}')
        self.add_hist_complete = 1

    def handle_socket_message(self, msg):
        try:
            if msg != '':
                payload = msg['k']
                if payload['x']:
                    if self.pop_previous_value:
                        self.remove_last_candle()
                    self.consume_new_candle(payload)
                    self.update_indicators()
                    if self.add_hist_complete:
                        log.info(f'Price update for {self.symbol}: Close: {self.Close[-1]}, RSI: {self.indicators["RSI"]["values"][-1]}, SMA: {self.indicators["SMA"]["values"][-1]}, ATR: {self.indicators["ATR"]["values"][-1]}')
                        trade_direction, stop_loss_val, take_profit_val= self.make_decision()
                        if trade_direction != -99:
                            if trade_direction == 1:
                                # Close all short positions at the market price
                                self.client.futures_create_order(
                                    symbol=self.symbol,
                                    side=SIDE_BUY,
                                    type=FUTURE_ORDER_TYPE_MARKET,
                                    quantity=self.get_short_position_qty()
                                )
                                # Cancel all short open limit orders
                                self.cancel_open_orders(side=SIDE_SELL)
                                # Cancel all stop market order (SIDE_BUY)
                                self.cancel_stop_market_orders(side=SIDE_BUY)
                                # Check if there is any long positions or open orders
                                if not self.get_long_position_qty() > 0 or self.has_open_orders(side=SIDE_BUY):
                                    stop_loss_val = self.indicators["ATR"]["values"][-1]
                                    self.signal_queue.put([self.symbol, self.OP, self.CP, self.tick_size, trade_direction, self.index, stop_loss_val, take_profit_val])
                            if trade_direction == 0:
                                # Close all long positions at the market price
                                self.client.futures_create_order(
                                    symbol=self.symbol,
                                    side=SIDE_SELL,
                                    type=FUTURE_ORDER_TYPE_MARKET,
                                    quantity=self.get_long_position_qty()
                                )
                                # Cancel all long open limit orders
                                self.cancel_open_orders(side=SIDE_BUY)
                                # Cancel all stop market order (SIDE_SELL)
                                self.cancel_stop_market_orders(side=SIDE_SELL)
                                # Check if there is any short position or open orders
                                if not self.get_short_position_qty() > 0 or self.has_open_orders(side=SIDE_SELL):
                                    stop_loss_val = self.indicators["ATR"]["values"][-1]
                                    self.signal_queue.put([self.symbol, self.OP, self.CP, self.tick_size, trade_direction, self.index, stop_loss_val, take_profit_val])
                        self.remove_first_candle()
                    if self.index == 0:
                        self.print_trades_q.put(True)
                    if not self.first_interval:
                        self.first_interval = True
                    self.pop_previous_value = False

        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            log.warning(f"handle_socket_message() - Error in handling of {self.symbol} websocket flagging for reconnection, msg: {msg}, Error Info: {exc_obj, fname, exc_tb.tb_lineno}, Error: {e}")
            self.socket_failed = True

    def get_short_position_qty(self):
        positions = self.client.futures_position_information(symbol=self.symbol)
        for position in positions:
            if float(position['positionAmt']) < 0:
                return abs(float(position['positionAmt']))
        return 0

    def get_long_position_qty(self):
        positions = self.client.futures_position_information(symbol=self.symbol)
        for position in positions:
            if float(position['positionAmt']) > 0:
                return float(position['positionAmt'])
        return 0

    def cancel_open_orders(self, side):
        orders = self.client.futures_get_open_orders(symbol=self.symbol)
        for order in orders:
            if order['side'] == side:
                self.client.futures_cancel_order(symbol=self.symbol, orderId=order['orderId'])

    def cancel_stop_market_orders(self, side):
        orders = self.client.futures_get_open_orders(symbol=self.symbol)
        for order in orders:
            if order['side'] == side and order['type'] in [FUTURE_ORDER_TYPE_STOP_MARKET,FUTURE_ORDER_TYPE_TAKE_PROFIT]:
                self.client.futures_cancel_order(symbol=self.symbol, orderId=order['orderId'])

    def has_open_orders(self, side):
        orders = self.client.futures_get_open_orders(symbol=self.symbol)
        for order in orders:
            if order['side'] == side:
                return True
        return False

    def make_decision(self):
        self.update_indicators()
        ##Initialize vars:
        trade_direction = -99  ## Short (0), Long (1)
        stop_loss_val = -99
        take_profit_val = -99
        ## Strategies found in strategy.py:
        try:
            match self.strategy:
                case 'RSI':
                    trade_direction = TS.RSI(trade_direction, self.Close, self.indicators["SMA"]["values"],
                                             self.indicators["RSI"]["values"], self.current_index)
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            log.error(f"make_decision() - Error with strategy: {self.strategy}, Error Info: {exc_obj, fname, exc_tb.tb_lineno}, Error: {e}")
        try:
            if trade_direction != -99:
                self.update_TP_SL()
                stop_loss_val = -99
                take_profit_val = -99  # That is worked out later by adding or subtracting:
                stop_loss_val = TS.SetSLTP(self.stop_loss_val, self.take_profit_val, self.peaks,
                                                            self.troughs, self.Close, self.High, self.Low, trade_direction,
                                                            self.SL_mult,
                                                            self.TP_mult, self.TP_SL_choice,
                                                            self.current_index)
                take_profit_val = -99

        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            log.error(
                f"make_decision() - Error with SetSLTP TP_SL_choice: {self.TP_SL_choice}, Error Info: {exc_obj, fname, exc_tb.tb_lineno}, Error: {e}")

        return trade_direction, stop_loss_val, take_profit_val

    def remove_last_candle(self):
        self.Date.pop(-1)
        self.Close.pop(-1)
        self.Volume.pop(-1)
        self.High.pop(-1)
        self.Low.pop(-1)
        self.Open.pop(-1)
        self.Open_H.pop(-1)
        self.Close_H.pop(-1)
        self.High_H.pop(-1)
        self.Low_H.pop(-1)

    def remove_first_candle(self):
        self.Date.pop(0)
        self.Close.pop(0)
        self.Volume.pop(0)
        self.High.pop(0)
        self.Low.pop(0)
        self.Open.pop(0)
        self.Open_H.pop(0)
        self.Close_H.pop(0)
        self.Low_H.pop(0)
        self.High_H.pop(0)

    def consume_new_candle(self, payload):
        self.Date.append(int(payload['T']))
        self.Close.append(float(payload['c']))
        self.Volume.append(float(payload['q']))
        self.High.append(float(payload['h']))
        self.Low.append(float(payload['l']))
        self.Open.append(float(payload['o']))

