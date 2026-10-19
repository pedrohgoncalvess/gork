import unittest
from unittest.mock import AsyncMock, Mock, patch

import main


class StartupPricingTests(unittest.IsolatedAsyncioTestCase):
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
