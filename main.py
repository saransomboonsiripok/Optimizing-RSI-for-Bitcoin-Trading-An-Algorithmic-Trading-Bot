import asyncio
from pprint import PrettyPrinter
from configuration import *
from configuration import symbols_to_trade  # explicitly importing to remove a warning
from configuration import buffer  # explicitly importing to remove a warning

from helper import *
from trademanager import *
from threading import Thread
import multiprocessing
from queue import Queue
import os

os.environ['TYPE_CHECKING'] = 'False'

if __name__ == '__main__':
    log.info(f'Configuration:\nleverage: {leverage}\n'
             f'interval: {interval}\nSL mult of ATR: {SL_mult}\n'
             f'symbols to trade: {symbols_to_trade}\n'
             f'RSI window: {RSI_window}\n RSI lower bound: {RSI_lower_bound}\n RSI upper bound: {RSI_upper_bound}\n'
             f'SMA window: {SMA_window}\n'
             )
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    pp = PrettyPrinter()
    Bots: [tradingbot.Bot] = []
    signal_queue = multiprocessing.Queue()
    print_trades_q = multiprocessing.Queue()

    python_binance_client = Client(api_key=API_KEY, api_secret=API_SECRET, testnet=True)
    client = CustomClient(python_binance_client)

    client.set_leverage(symbols_to_trade)

    ## Initialize a bot for each coin we're trading
    client.setup_bots(Bots, symbols_to_trade, signal_queue, print_trades_q)
    client.start_websockets(Bots)

    ## Initialize Trade manager for order related tasks
    TM = None
    new_trade_loop = multiprocessing.Process(target=start_new_trades_loop_multiprocess, args=(python_binance_client, signal_queue, print_trades_q))
    new_trade_loop.start()

    ## Thread to ping the server & reconnect websockets
    ping_server_reconnect_sockets_thread = Thread(target=client.ping_server_reconnect_sockets, args=(Bots,))
    ping_server_reconnect_sockets_thread.daemon = True
    ping_server_reconnect_sockets_thread.start()

    ## Combine data collected from websockets with historical data, so we have a buffer of data to calculate signals
    combine_data_thread = Thread(target=client.combine_data, args=(Bots, symbols_to_trade, buffer))
    combine_data_thread.daemon = True
    combine_data_thread.start()
    new_trade_loop.join()