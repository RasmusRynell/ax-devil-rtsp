"""Failures shared by the session, protocol and transport layers."""


class StreamError(Exception):
    """A connection, protocol or decoding failure of a stream session.

    The message never contains credentials, and the third-party exception that caused it is not chained.
    """
