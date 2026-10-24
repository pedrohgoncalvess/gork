import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from database.models.manager import Interaction
from database.operations.manager import InteractionRepository
from database.operations.manager.interaction import MissingModelPriceError
from agents._shared.conversation import _record_conversation_interaction
from services.model_pricing import (
    model_price_values,
    refresh_model_prices_and_reschedule,
    set_model_price_refresh,
)


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
    async def test_initial_and_recurring_timer_start_after_fetch_finishes(self):
        started = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
        finished = started + timedelta(minutes=3)
        for schedule in (set_model_price_refresh, refresh_model_prices_and_reschedule):
            with self.subTest(schedule=schedule.__name__):
                scheduler = Mock()
                with patch("services.model_pricing.datetime") as clock:
                    clock.now.return_value = started

                    async def fetch():
                        scheduler.add_job.assert_not_called()
                        clock.now.return_value = finished

                    with patch(
                        "services.model_pricing.refresh_model_prices_safely",
                        new=AsyncMock(side_effect=fetch),
                    ) as refresh:
                        await schedule(scheduler)

                refresh.assert_awaited_once_with()
                scheduler.add_job.assert_called_once()
                self.assertEqual(
                    scheduler.add_job.call_args.kwargs["run_date"],
                    finished + timedelta(hours=2),
                )

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
    async def test_missing_snapshot_is_fetched_and_persisted_with_interaction(self):
        empty, model_result = Mock(), Mock()
        empty.scalar_one_or_none.return_value = None
        model_result.scalar_one_or_none.return_value = SimpleNamespace(openrouter_id="new/model")
        db = Mock()
        db.execute = AsyncMock(side_effect=[empty, model_result])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        async def flush():
            db.add.call_args.args[0].id = 77

        db.flush = AsyncMock(side_effect=flush)
        repository = InteractionRepository(Interaction, db)
        with patch("external.openrouter.get_models", new=AsyncMock(return_value=[
            {"id": "new/model", "pricing": {"prompt": "0.000001", "completion": "0.000002"}}
        ])) as catalog:
            interaction = await repository.create_interaction(
                model_id=76, user_id=9, group_id=1, user_prompt="hello",
                input_tokens=4, output_tokens=2, actual_cost=0.003,
            )
        catalog.assert_awaited_once()
        price = db.add.call_args_list[0].args[0]
        self.assertEqual(price.model_id, 76)
        self.assertEqual(price.prompt_price, Decimal("0.000001"))
        self.assertEqual(interaction.model_price_id, 77)
        self.assertEqual(interaction.actual_cost, 0.003)
        db.commit.assert_awaited_once()

    async def test_missing_catalog_price_does_not_invent_zero_cost(self):
        for catalog_error in (False, True):
            with self.subTest(catalog_error=catalog_error):
                empty, model_result = Mock(), Mock()
                empty.scalar_one_or_none.return_value = None
                model_result.scalar_one_or_none.return_value = SimpleNamespace(openrouter_id="new/model")
                db = Mock(execute=AsyncMock(side_effect=[empty, model_result]))
                catalog = AsyncMock(return_value=[])
                if catalog_error:
                    catalog.side_effect = RuntimeError("catalog offline")
                with patch("external.openrouter.get_models", new=catalog):
                    with self.assertRaises(MissingModelPriceError):
                        await InteractionRepository(Interaction, db).create_interaction(
                            model_id=76, user_id=9, group_id=1, user_prompt="hello", input_tokens=4,
                        )
                db.add.assert_not_called()

    async def test_unpriced_usage_does_not_block_completed_conversation(self):
        repository = SimpleNamespace(create_interaction=AsyncMock(side_effect=MissingModelPriceError("missing")))
        with patch("agents._shared.conversation.logger.warn", new=AsyncMock()) as warn:
            await _record_conversation_interaction(
                repository, model_id=76, user_id=9, group_id=1,
                input_tokens=4, output_tokens=2, actual_cost=0.003,
            )
        self.assertEqual(warn.call_args.args[1], "ConversationUsageUnpriced")
        self.assertIn("input_tokens=4", warn.call_args.args[2])
        self.assertIn("actual_cost=0.003", warn.call_args.args[2])

    async def test_unrelated_database_errors_are_not_silenced(self):
        repository = SimpleNamespace(create_interaction=AsyncMock(side_effect=RuntimeError("database offline")))
        with self.assertRaisesRegex(RuntimeError, "database offline"):
            await _record_conversation_interaction(repository, model_id=76)

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
