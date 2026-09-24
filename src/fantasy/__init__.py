# api.sleeper.app drops the occasional TLS handshake and `sleeper_wrapper`
# retries nothing, which used to fail whichever rebuild step was unlucky.
# Every Sleeper call in this package goes through that library, so the patch
# is installed here rather than at each of the dozen call sites.
from fantasy import sleeper_retry

sleeper_retry.install()
