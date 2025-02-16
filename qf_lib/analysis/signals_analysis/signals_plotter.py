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
import inspect
from datetime import datetime
from typing import Union, Sequence, Dict

import matplotlib as plt
from pandas import date_range

from qf_lib.analysis.common.abstract_document import AbstractDocument
from qf_lib.backtesting.alpha_model.alpha_model import AlphaModel
from qf_lib.backtesting.alpha_model.exposure_enum import Exposure
from qf_lib.backtesting.data_handler.data_handler import DataHandler
from qf_lib.backtesting.events.time_event.regular_time_event.market_close_event import MarketCloseEvent
from qf_lib.backtesting.events.time_event.regular_time_event.market_open_event import MarketOpenEvent
from qf_lib.common.enums.frequency import Frequency
from qf_lib.common.enums.price_field import PriceField
from qf_lib.common.exceptions.future_contracts_exceptions import NoValidTickerException
from qf_lib.common.tickers.tickers import Ticker
from qf_lib.common.utils.dateutils.timer import SettableTimer
from qf_lib.common.utils.error_handling import ErrorHandling
from qf_lib.common.utils.miscellaneous.to_list_conversion import convert_to_list
from qf_lib.containers.futures.future_tickers.future_ticker import FutureTicker
from qf_lib.containers.futures.futures_adjustment_method import FuturesAdjustmentMethod
from qf_lib.containers.futures.futures_chain import FuturesChain
from qf_lib.containers.series.qf_series import QFSeries
from qf_lib.documents_utils.document_exporting.element.chart import ChartElement
from qf_lib.documents_utils.document_exporting.element.custom import CustomElement
from qf_lib.documents_utils.document_exporting.element.heading import HeadingElement
from qf_lib.documents_utils.document_exporting.element.new_page import NewPageElement
from qf_lib.documents_utils.document_exporting.element.paragraph import ParagraphElement
from qf_lib.documents_utils.document_exporting.pdf_exporter import PDFExporter
from qf_lib.plotting.charts.candlestick_chart import CandlestickChart
from qf_lib.settings import Settings


@ErrorHandling.class_error_logging()
class SignalsPlotter(AbstractDocument):
    """
    Generates a document with candlestick charts for each given ticker and highlights the background to indicate at
    which time a position has been opened. LONG positions are highlighted green, SHORT positions are highlighted red.

    The plots can be generated either:
    - to show exact dates when LONG / SHORT entry signals were generated (only_entry_signals = True)
    - to show when LONG / SHORT position should be opened and closed, based on the signals generated by alpha models
    (only_entry_signals = False).

    Parameters
    -----------
    tickers: Ticker, Sequence[Ticker]
        tickers for which the prices will be plotted. The list can also contain FutureTickers - in this case the prices
        presented in the form of the candlestick chart, will be built using the FuturesChain object (without any
        backward adjustment).
    start_date: datetime
        starting date of the prices data frame
    end_date: datetime
        last date of the prices data frame
    data_handler: DataHandler
        data handler used to download prices
    alpha_models: AlphaModel, Sequence[AlphaModel]
        instances of alpha models which signals will be evaluated. Each plot in the document is described using the
        alpha_models __str__ function.
    settings: Settings
        settings used to connect to db
    pdf_exporter: PDFExporter
        pdf exporter
    only_entry_signals: bool
        if set to True only the entry signals are highlighted, if set to False - all the hold timeperiod is highlighted
    title: str
        title of the document
    """

    def __init__(self, tickers: Union[Ticker, Sequence[Ticker]], start_date: datetime, end_date: datetime,
                 data_handler: DataHandler, alpha_models: Union[AlphaModel, Sequence[AlphaModel]], settings: Settings,
                 pdf_exporter: PDFExporter, only_entry_signals: bool = True, title: str = "Signals Plotter"):

        super().__init__(settings, pdf_exporter, title)

        # Set the market open and close events in order to use the data handler (necessary to e.g. compute the market
        # close time of the previous day)
        MarketOpenEvent.set_trigger_time({"hour": 13, "minute": 30, "second": 0, "microsecond": 0})
        MarketCloseEvent.set_trigger_time({"hour": 20, "minute": 0, "second": 0, "microsecond": 0})

        self.tickers, _ = convert_to_list(tickers, Ticker)
        self.alpha_models, _ = convert_to_list(alpha_models, AlphaModel)

        self.start_date = start_date
        self.end_date = end_date

        self.data_handler = data_handler

        assert isinstance(self.data_handler.timer, SettableTimer)
        self.timer: SettableTimer = self.data_handler.timer

        self.only_entry_signals = only_entry_signals

        for ticker in tickers:
            if isinstance(ticker, FutureTicker):
                ticker.initialize_data_provider(self.timer, self.data_handler.data_provider)

    def build_document(self):
        self._add_header()

        for ticker in self.tickers:
            self.create_tickers_analysis(ticker)
            self.document.add_element(NewPageElement())

        self.add_models_implementation()

    def create_tickers_analysis(self, ticker: Ticker):
        """
        For the given ticker add candlestick charts representing OHLC prices with highlighted signals generated by each
        of the alpha models. In case if the model generates a BUY signal the background for the given day is highlighted
        with green color, in case of a SELL signal - red.
        """
        prices_df = self.get_prices(ticker)
        alpha_model_signals: Dict[AlphaModel, QFSeries] = {}

        self.document.add_element(HeadingElement(level=2, text=ticker.name))

        for alpha_model in self.alpha_models:
            exposures = []
            dates = []

            prev_exposure = Exposure.OUT

            for date in date_range(self.start_date, self.end_date, freq="B"):
                try:
                    self.timer.set_current_time(date)
                    new_exposure = alpha_model.get_signal(ticker, prev_exposure, date, Frequency.DAILY)\
                        .suggested_exposure
                    exposures.append(new_exposure.value)
                    dates.append(date)

                    if not self.only_entry_signals:
                        prev_exposure = new_exposure
                except NoValidTickerException as e:
                    print(e)

            exposures_series = QFSeries(data=exposures, index=dates)
            alpha_model_signals[alpha_model] = exposures_series

            candlestick_chart = CandlestickChart(prices_df, title=str(alpha_model))
            candlestick_chart.add_highlight(exposures_series)
            self.document.add_element(ChartElement(candlestick_chart, figsize=self.full_image_size, dpi=self.dpi))

        candlestick_chart = CandlestickChart(prices_df, title="All models summary")
        for model, exposures_series in alpha_model_signals.items():
            candlestick_chart.add_highlight(exposures_series)

        self.document.add_element(ChartElement(candlestick_chart, figsize=self.full_image_size, dpi=self.dpi))

    def get_prices(self, ticker: Ticker):
        """
        Create a data frame with OHLC prices for the given ticker.
        """
        self.timer.set_current_time(self.end_date)

        if isinstance(ticker, FutureTicker):
            futures_chain = FuturesChain(ticker, self.data_handler, method=FuturesAdjustmentMethod.NTH_NEAREST)
            prices_df = futures_chain.get_price([PriceField.Open, PriceField.High, PriceField.Low, PriceField.Close],
                                                start_date=self.start_date,
                                                end_date=self.end_date,
                                                frequency=self.data_handler.frequency)
        else:
            prices_df = self.data_handler.get_price(ticker,
                                                    [PriceField.Open, PriceField.High, PriceField.Low,
                                                     PriceField.Close],
                                                    start_date=self.start_date,
                                                    end_date=self.end_date,
                                                    frequency=self.data_handler.frequency)
        return prices_df

    def add_models_implementation(self):
        """
        Add the source code of the classes (in order to simplify the implementation the full contents of the file
        containing.

        If there are multiple alpha models which are different instances of the same class, the implementation will be
        printed only once.
        """
        alpha_model_types = {alpha_model.__class__ for alpha_model in self.alpha_models}
        for model_type in alpha_model_types:
            self.document.add_element(HeadingElement(2, "Implementation of {}".format(model_type.__name__)))
            self.document.add_element(ParagraphElement("\n"))

            with open(inspect.getfile(model_type)) as f:
                class_implementation = f.read()
            # Remove the imports section
            class_implementation = "<pre>class {}".format(model_type.__name__) + \
                                   class_implementation.split("class {}".format(model_type.__name__))[1] + "</pre>"
            self.document.add_element(CustomElement(class_implementation))

    def save(self, report_dir: str = ""):
        # Set the style for the report
        plt.style.use(['tearsheet'])

        file_name = "%Y_%m_%d-%H%M {}.pdf".format(self.title)
        file_name = datetime.now().strftime(file_name)

        if not file_name.endswith(".pdf"):
            file_name = "{}.pdf".format(file_name)

        return self.pdf_exporter.generate([self.document], report_dir, file_name)
