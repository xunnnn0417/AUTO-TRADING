"""Leftover Funnel sessions of this helper are cleared; nothing else is touched."""
import unittest
from unittest.mock import patch

from trading_helper import remote_tunnel

ORIGIN = 'http://127.0.0.1:8765'
CMD = '"C:\Program Files\Tailscale\tailscale.exe"  funnel --https=8443 ' + ORIGIN


class StaleFunnelTests(unittest.TestCase):
    def test_only_own_or_orphaned_funnels_for_this_origin(self):
        processes = [
            (11, 500, CMD),                      # child of this helper -> stale
            (12, 999, CMD),                      # parent gone -> orphan of an old run
            (13, 600, CMD),                      # parent alive (a user terminal) -> keep
            (14, 500, 'tailscale.exe status'),   # not a funnel -> keep
            (15, 500, CMD.replace('8765', '9000')),  # other origin -> keep
        ]
        with patch.object(remote_tunnel, '_alive_pids', return_value=[500, 600]):
            pids = remote_tunnel.stale_funnel_pids(ORIGIN, own_pid=500, processes=processes)
        self.assertEqual(pids, [11, 12])


if __name__ == '__main__':
    unittest.main()
