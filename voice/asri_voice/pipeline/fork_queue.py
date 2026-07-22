"""ForkQueue — a write-only queue wrapper that fans out to multiple downstream queues.

Used to fork a single producer's output to multiple consumers without
modifying the producer.  For example, VAD output can be sent to both
STT (main pipeline) and the HeartBeatInteraction handler (side branch).

Usage::

    from queue import Queue
    from pipeline.fork_queue import ForkQueue

    main_queue = Queue()
    side_queue = Queue()
    fork = ForkQueue(main_queue, side_queue)

    # Producer writes to fork — both queues receive the item
    fork.put(item)

    # Consumers read from their own queues
    main_queue.get()
    side_queue.get()
"""

import logging

logger = logging.getLogger(__name__)


class ForkQueue:
    """Write-only queue that copies every ``put()`` to all downstream queues.

    Implements the subset of ``queue.Queue`` interface needed by
    ``BaseHandler`` as a ``queue_out`` replacement.  Reading (``get()``)
    is not supported — consumers should read from the individual
    downstream queues directly.
    """

    def __init__(self, *downstream_queues):
        if not downstream_queues:
            raise ValueError("ForkQueue requires at least one downstream queue")
        self.downstreams = list(downstream_queues)

    def put(self, item, block=True, timeout=None):
        """Put *item* into every downstream queue."""
        for queue in self.downstreams:
            queue.put(item, block=block, timeout=timeout)

    def put_nowait(self, item):
        """Non-blocking put into every downstream queue."""
        for queue in self.downstreams:
            queue.put_nowait(item)

    def get(self, *args, **kwargs):
        raise NotImplementedError(
            "ForkQueue is write-only. Read from downstream queues directly."
        )

    def get_nowait(self):
        raise NotImplementedError(
            "ForkQueue is write-only. Read from downstream queues directly."
        )
