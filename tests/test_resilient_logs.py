from houseedge.data.base_rpc import get_event_logs_resilient


class FakeEventCall:
    def __init__(self,parent): self.parent=parent
    def get_logs(self,from_block,to_block,**kwargs):
        if to_block-from_block+1>2:
            raise RuntimeError("response too large")
        return list(range(from_block,to_block+1))


class FakeEvent:
    def __call__(self): return FakeEventCall(self)


def test_resilient_log_fetch_splits_rejected_ranges():
    out=get_event_logs_resilient(FakeEvent(),from_block=1,to_block=6,retries=0)
    assert out==[1,2,3,4,5,6]
