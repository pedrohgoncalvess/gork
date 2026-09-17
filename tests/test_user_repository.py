import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from database.operations.base.user import UserRepository


class UserRepositoryIdentityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repository = UserRepository(AsyncMock())
        self.repository.find_by_lid = AsyncMock(return_value=None)
        self.repository.find_by_phone = AsyncMock()
        self.repository.update = AsyncMock()
        self.repository.insert = AsyncMock()

    async def test_reuses_existing_user_when_dm_has_phone_in_both_jids(self):
        user = SimpleNamespace(
            id=7,
            src_id="161323350499368",
            phone_number="554899865556",
            name="Pedro",
        )
        self.repository.find_by_phone.return_value = user
        self.repository.update.return_value = user

        result = await self.repository.find_or_create(
            lid="554899865556",
            phone_number="554899865556",
            name="Pedro",
        )

        self.assertIs(result, user)
        self.repository.find_by_lid.assert_not_awaited()
        self.repository.insert.assert_not_awaited()
        self.repository.update.assert_awaited_once_with(7, {"name": "Pedro"})

    async def test_reconciles_phone_only_user_when_real_lid_arrives(self):
        user = SimpleNamespace(
            id=8,
            src_id="554899865556",
            phone_number="554899865556",
            name="Pedro",
        )
        self.repository.find_by_phone.return_value = user
        updated_user = SimpleNamespace(**vars(user), extra="updated")
        self.repository.update.return_value = updated_user

        result = await self.repository.find_or_create(
            lid="161323350499368",
            phone_number="554899865556",
            name="Pedro",
        )

        self.assertIs(result, updated_user)
        self.repository.insert.assert_not_awaited()
        self.repository.update.assert_awaited_once_with(
            8,
            {"name": "Pedro", "src_id": "161323350499368"},
        )

    async def test_phone_lookup_prioritizes_whitelisted_identity(self):
        user = SimpleNamespace(id=7)
        scalar_result = Mock()
        scalar_result.scalar_one_or_none.return_value = user
        db = AsyncMock()
        db.execute.return_value = scalar_result

        result = await UserRepository(db).find_by_phone("554899865556")

        self.assertIs(result, user)
        statement = db.execute.await_args.args[0]
        sql = str(statement)
        self.assertIn("LEFT OUTER JOIN base.white_list", sql)
        self.assertIn("base.white_list.deleted_at IS NULL", sql)
        self.assertIn(
            "ORDER BY base.white_list.id IS NULL, base.\"user\".id ASC",
            sql,
        )
        self.assertIn("LIMIT", str(statement))


if __name__ == "__main__":
    unittest.main()
