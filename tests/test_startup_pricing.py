import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

import main


class StartupPricingTests(unittest.IsolatedAsyncioTestCase):
    async def test_periodic_jobs_start_now_with_an_explicit_timezone(self):
        scheduler = Mock()
        before = datetime.now(timezone.utc)
        with (patch('main.apply_pending_migrations', return_value=0),
              patch('main.logger.info', AsyncMock()),
              patch('main.init_agents', AsyncMock()), patch('main.init_assets', AsyncMock()),
              patch('main.set_model_price_refresh', AsyncMock()), patch('main.set_remembers', AsyncMock()),
              patch('main.scheduler', scheduler)):
            await main.startup_event()
        jobs = {call.kwargs['id']: call.kwargs for call in scheduler.add_job.call_args_list}
        for name in ('group-ban-polls', 'automatic-setup'):
            first_run = jobs[name]['next_run_time']
            self.assertIsNotNone(first_run.tzinfo)
            self.assertLess(abs((first_run - before).total_seconds()), 5)
        self.assertEqual(jobs['group-ban-polls']['seconds'], 5)

    async def test_new_agent_models_are_registered_before_price_refresh(self):
        order = []

        async def agents():
            order.append("agents")

        async def prices(scheduler):
            order.append("prices")

        with (
            patch("main.apply_pending_migrations", return_value=0),
            patch("main.logger.info", new=AsyncMock()),
            patch("main.init_agents", new=AsyncMock(side_effect=agents)),
            patch("main.set_model_price_refresh", new=AsyncMock(side_effect=prices)),
            patch("main.init_assets", new=AsyncMock()),
            patch("main.set_remembers", new=AsyncMock()),
            patch("main.scheduler", new=Mock()),
        ):
            await main.startup_event()

        self.assertEqual(order, ["agents", "prices"])


if __name__ == "__main__":
    unittest.main()
