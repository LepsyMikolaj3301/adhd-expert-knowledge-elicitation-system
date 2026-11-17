"""Errors a job can end with. They are separate from the handlers so that the code a handler calls
(`app.knowledge.ingest`) can raise them without importing the handlers."""


class PermanentJobError(Exception):
    """Retrying can't help, so the job fails at once instead of using up its attempts."""


class NoFindings(PermanentJobError):
    """The check was passed but there is nothing to build from."""


class NoUnits(PermanentJobError):
    pass


class UnitsNotEmbeddable(PermanentJobError):
    """Units from before the pipeline (the verbatim stub) have no text to embed."""
