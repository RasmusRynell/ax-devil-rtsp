import time

def wait_for_all(events, timeout):
    """
    Waits for all threading.Event objects in `events` to be set, with a shared timeout.
    Returns True if all events were set, False if timeout occurred.
    """
    deadline = time.time() + timeout
    for event in events:
        remaining = deadline - time.time()
        if remaining <= 0 or not event.wait(timeout=remaining):
            return False
    return True