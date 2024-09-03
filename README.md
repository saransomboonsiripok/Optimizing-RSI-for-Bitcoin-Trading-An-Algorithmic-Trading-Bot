# Optimizing RSI for Bitcoin Trading: An Algorithmic Trading Bot

This project, part of the QF635 - Market Microstructure and Algorithmic Trading course at Bayes Business School under the guidance of Prof. Nicholas Liew, focuses on optimizing the Relative Strength Index (RSI) for Bitcoin trading. The project involves leveraging the Binance Testnet to implement and test an automated trading bot. The bot is designed to adapt to market conditions by dynamically adjusting RSI thresholds and incorporating a Simple Moving Average (SMA) filter to enhance signal accuracy.

## Key Features
- Dynamic RSI Strategy: Utilizes optimized RSI thresholds for entry and exit points in trading Bitcoin, with a focus on maximizing returns while minimizing risk.
= Stop-Loss and Position Sizing: Implements ATR-based stop-loss mechanisms and an averaging down method to manage risk and enhance profitability.
= Backtesting and Optimization: The strategy was backtested on historical data to optimize the RSI window and thresholds, achieving the highest Sharpe ratio and lowest drawdown.
= Automated Trading Bot: Built using Python, the bot connects to the Binance Testnet API, handles real-time data streaming, and executes trades based on the optimized RSI strategy.

## Repository Contents
- 0 - Backtesting Code - RSI - rev_3.ipynb: Jupyter notebook for backtesting the RSI strategy, including the optimization of RSI parameters and evaluation of strategy performance.
- configuration.py: Contains key settings, including API credentials, RSI parameters, and trading configurations.
- logger.py: Sets up logging for the bot using the colorlog library for enhanced readability.
- strategy.py: Implements the RSI trading strategy, generating buy/sell signals based on RSI and SMA values.
- helper.py: Includes utility functions and a custom client class for interacting with the Binance API and managing historical data.
- tradingbot.py: Defines the main Bot class, encapsulating the trading logic and handling real-time data and trade execution.
- trademanager.py: Manages trade execution and monitoring, ensuring that all trades are tracked and managed efficiently.
- main.py: Orchestrates the overall operation of the bot, initializing components, starting the trading bots, and managing trades.

## Results and Performance
- Optimized RSI Parameters: The backtesting phase identified the optimal RSI window of 35 with upper and lower bounds set at 85 and 30, respectively, using a 1-minute candlestick interval.
- Superior Returns: The RSI strategy outperformed the Buy and Hold strategy during backtesting, achieving a higher cumulative return and Sharpe ratio.
- Robust Risk Management: The strategy effectively managed risks through ATR-based stop-losses and dynamic position sizing, resulting in lower drawdowns and more stable returns.
