import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from database.models.manager import Interaction
from database.operations.manager import InteractionRepository
from services.model_pricing import model_price_values, set_model_price_refresh


class ModelPricingTests(unittest.TestCase):
    def test_openrouter_prices_keep_per_unit_precision_and_raw_fields(self):
        pricing = {
            "prompt": "0.00000014",
            "completion": "0.00000028",
            "image": "0.04",
            "audio": "0.000001",
            "overrides": [{"min_prompt_tokens": 200000, "prompt": "0.00000028"}],
        }

        values = model_price_values(7, pricing)

        self.assertEqual(values["model_id"], 7)
        self.assertEqual(values["prompt_price"], Decimal("0.00000014"))
        self.assertEqual(values["completion_price"], Decimal("0.00000028"))
        self.assertEqual(values["image_price"], Decimal("0.04"))
        self.assertEqual(values["pricing"]["audio"], "0.000001")
        self.assertEqual(values["pricing"]["overrides"], pricing["overrides"])

    def test_video_skus_are_preserved_for_non_token_pricing(self):
        pricing = {
            "video_skus": {
                "5s-480p": "0.12",
                "10s-1080p-audio": "0.85",
            }
        }

        values = model_price_values(9, pricing)

        self.assertEqual(values["pricing"]["video_skus"], pricing["video_skus"])

    def test_unknown_or_invalid_explicit_price_is_nullable_but_preserved(self):
        pricing = {"prompt": "not-a-number", "video": {"usd": "0.10"}}

        values = model_price_values(1, pricing)

        self.assertIsNone(values["prompt_price"])
        self.assertEqual(values["pricing"]["video"], {"usd": "0.10"})


class ModelPricingScheduleTests(unittest.IsolatedAsyncioTestCase):
    async def test_initial_refresh_anchors_non_catch_up_two_hour_interval(self):
        scheduler = unittest.mock.Mock()

        with patch(
            "services.model_pricing.refresh_model_prices_safely",
            new=AsyncMock(),
        ) as refresh:
            before = datetime.now(timezone.utc)
            await set_model_price_refresh(scheduler)
            after = datetime.now(timezone.utc)

        refresh.assert_awaited_once_with()
        scheduler.add_job.assert_called_once()
        call = scheduler.add_job.call_args
        self.assertEqual(call.args[1], "date")
        self.assertEqual(call.kwargs["id"], "openrouter-model-prices")
        self.assertEqual(call.kwargs["args"], [scheduler])
        self.assertTrue(call.kwargs["replace_existing"])
        self.assertGreaterEqual(call.kwargs["run_date"], before + timedelta(hours=2))
        self.assertLessEqual(call.kwargs["run_date"], after + timedelta(hours=2))


class InteractionPricingTests(unittest.IsolatedAsyncioTestCase):
    async def test_interaction_points_to_latest_resolved_price_snapshot(self):
        price = SimpleNamespace(id=17)
        result = Mock()
        result.scalar_one_or_none.return_value = price
        db = Mock()
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        repository = InteractionRepository(Interaction, db)

        interaction = await repository.create_interaction(
            model_id=3,
            user_id=9,
            group_id=None,
            user_prompt="hello",
            input_tokens=4,
            output_tokens=2,
        )

        self.assertEqual(interaction.model_price_id, 17)
        self.assertFalse(hasattr(interaction, "model_id"))
        db.add.assert_called_once_with(interaction)


if __name__ == "__main__":
    unittest.main()
