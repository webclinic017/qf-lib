#     Copyright 2016-present CERN – European Organization for Nuclear Research
#
#     Licensed under the Apache License, Version 2.0 (the "License");
#     you may not use this file except in compliance with the License.
#     You may obtain a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#     Unless required by applicable law or agreed to in writing, software
#     distributed under the License is distributed on an "AS IS" BASIS,
#     WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#     See the License for the specific language governing permissions and
#     limitations under the License.
import matplotlib.pyplot as plt

from qf_lib.backtesting.strategies.signal_generators import OnBeforeMarketOpenSignalGeneration

plt.ion()  # required for dynamic chart, good to keep this at the beginning of imports

from demo_scripts.backtester.moving_average_alpha_model import MovingAverageAlphaModel
from demo_scripts.demo_configuration.demo_ioc import container
from qf_lib.backtesting.strategies.alpha_model_strategy import AlphaModelStrategy
from qf_lib.backtesting.contract.contract_to_ticker_conversion.quandl_mapper import DummyQuandlContractTickerMapper
from qf_lib.backtesting.execution_handler.commission_models.ib_commission_model import IBCommissionModel
from qf_lib.backtesting.position_sizer.initial_risk_position_sizer import InitialRiskPositionSizer
from qf_lib.backtesting.trading_session.backtest_trading_session_builder import BacktestTradingSessionBuilder
from qf_lib.common.enums.frequency import Frequency
from qf_lib.common.tickers.tickers import QuandlTicker
from qf_lib.common.utils.dateutils.string_to_date import str_to_date


def main():
    initial_risk = 0.03

    start_date = str_to_date('2016-01-01')
    end_date = str_to_date('2017-12-31')

    # ----- build trading session ----- #
    session_builder = container.resolve(BacktestTradingSessionBuilder)  # type: BacktestTradingSessionBuilder
    session_builder.set_backtest_name('Moving Average Alpha Model Backtest')
    session_builder.set_position_sizer(InitialRiskPositionSizer, initial_risk=initial_risk)
    session_builder.set_contract_ticker_mapper(DummyQuandlContractTickerMapper())
    session_builder.set_commission_model(IBCommissionModel)
    session_builder.set_frequency(Frequency.DAILY)
    ts = session_builder.build(start_date, end_date)

    # ----- build models ----- #
    model = MovingAverageAlphaModel(fast_time_period=5, slow_time_period=20, risk_estimation_factor=1.25,
                                    data_provider=ts.data_handler)
    model_tickers = [QuandlTicker('AAPL', 'WIKI'), QuandlTicker('AMZN', 'WIKI')]
    model_tickers_dict = {model: model_tickers}

    # ----- preload price data ----- #
    ts.use_data_preloading(model_tickers)

    # ----- start trading ----- #
    OnBeforeMarketOpenSignalGeneration(AlphaModelStrategy(ts, model_tickers_dict, use_stop_losses=True))
    ts.start_trading()

    # ----- use results ----- #
    backtest_tms = ts.portfolio.portfolio_eod_series().to_log_returns()
    print("mean daily log return: {}".format(backtest_tms.mean()))
    print("std of daily log returns: {}".format(backtest_tms.std()))


if __name__ == "__main__":
    main()
