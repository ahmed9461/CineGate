class HistoricalImportError(RuntimeError):
    pass


class ImportAlreadyRunning(HistoricalImportError):
    pass


class UserBotUnauthorized(HistoricalImportError):
    pass


class SourceForwardingRestricted(HistoricalImportError):
    pass


class ImportChannelAccessError(HistoricalImportError):
    pass


class ImportFloodWaitTooLong(HistoricalImportError):
    def __init__(self, seconds: int) -> None:
        super().__init__(f"Telegram FloodWait is too long: {seconds} seconds")
        self.seconds = seconds
