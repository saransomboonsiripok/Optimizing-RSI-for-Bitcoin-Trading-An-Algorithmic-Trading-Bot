from configuration import *
from logger import *

def RSI(Trade_Direction, Close, SMA100, RSI, current_index):
    if Close[current_index] < SMA100[current_index] and RSI[current_index] < RSI_lower_bound:
        Trade_Direction = 1  ##Buy
    elif Close[current_index] > SMA100[current_index] and RSI[current_index] > RSI_upper_bound:
        Trade_Direction = 0  ##Sell
    return Trade_Direction

def SetSLTP(stop_loss_val_arr, take_profit_val_arr, peaks, troughs, Close, High, Low, Trade_Direction, SL, TP, TP_SL_choice, current_index):
    take_profit_val = take_profit_val_arr[current_index]
    stop_loss_val = stop_loss_val_arr[current_index]
    return stop_loss_val, take_profit_val