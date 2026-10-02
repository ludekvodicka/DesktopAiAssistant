class UpdateError(Exception):
    """An update failure whose message is fit for the update UI."""


class UpdateHttpError(UpdateError):
    status: int
    url: str

    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"The update server answered HTTP {status}.")
        self.status = status
        self.url = url


class UpdateIntegrityError(UpdateError):
    pass


class UpdateManifestError(UpdateError):
    pass
