"""AniRSS desktop UI public API."""

from .controller import AniRSSController, DemoController
from .dialogs import SubscriptionDialog
from .downloads import DownloadsPage
from .main_window import MainWindow
from .overview import OverviewPage
from .settings import SettingsPage
from .subscription_detail import SubscriptionDetailView
from .subscriptions import SubscriptionsPage
from .theme import ThemeManager, build_stylesheet

__all__ = [
    "AniRSSController",
    "DemoController",
    "DownloadsPage",
    "MainWindow",
    "OverviewPage",
    "SettingsPage",
    "SubscriptionDetailView",
    "SubscriptionDialog",
    "SubscriptionsPage",
    "ThemeManager",
    "build_stylesheet",
]
