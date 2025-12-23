from typing import Optional, List
from datetime import datetime, timedelta

from sqlalchemy.orm import joinedload
from sqlalchemy import select, and_, desc

from database.models.base import User
from database.models.content import Message
from database.operations import BaseRepository


class MessageRepository(BaseRepository[Message]):
    async def find_by_message_id(self, message_id: str) -> Optional[Message]:
        return await self.find_one_by(message_id=message_id)

    async def find_by_sender(self, sender_id: int, limit: int = 50) -> List[Message]:
        result = await self.db.execute(
            select(Message)
            .options(joinedload(Message.sender))
            .filter(
                and_(
                    Message.user_id == sender_id,
                    Message.deleted_at.is_(None)
                )
            )
            .order_by(desc(Message.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def find_by_group(self, group_id: int, limit: int = 50) -> List[Message]:
        result = await self.db.execute(
            select(Message)
            .options(joinedload(Message.sender))
            .filter(
                and_(
                    Message.group_id == group_id,
                    Message.deleted_at.is_(None)
                )
            )
            .order_by(desc(Message.created_at))
            .limit(limit)
        )
        return list(result.unique().scalars().all())

    async def find_group_messages_by_sender(
            self,
            group_id: int,
            sender_id: int,
            limit: int = 50
    ) -> List[Message]:
        result = await self.db.execute(
            select(Message)
            .filter(
                and_(
                    Message.group_id == group_id,
                    Message.user_id == sender_id,
                    Message.deleted_at.is_(None)
                )
            )
            .order_by(desc(Message.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def find_recent_messages(
            self,
            minutes: int = 5,
            group_id: int = None,
            sender_id: int = None
    ) -> List[Message]:
        time_threshold = datetime.now() - timedelta(minutes=minutes)

        filters = [
            Message.created_at >= time_threshold,
            Message.deleted_at.is_(None)
        ]

        if group_id:
            filters.append(Message.group_id == group_id)
        if sender_id:
            filters.append(Message.user_id == sender_id)

        result = await self.db.execute(
            select(Message)
            .filter(and_(*filters))
            .order_by(desc(Message.created_at))
        )
        return list(result.scalars().all())

    async def remove_favorite_message(self, message_id: str) -> Optional[Message]:
        message = await self.find_by_message_id(message_id)
        if not message:
            return None

        update_data = {"is_favorite": False}
        return await self.update(message.id, update_data)

    async def find_favorites_messages(
            self,
            last_days: int = None,
            group_id: int = None,
            user_id: int = None,
            user_name: str = None
    ) -> List[Message]:
        filters = [
            Message.deleted_at.is_(None),
            Message.is_favorite.is_(True)
        ]

        if last_days:
            time_threshold = datetime.now() - timedelta(days=last_days)
            filters.append(Message.created_at >= time_threshold)

        if group_id:
            filters.append(Message.group_id == group_id)
        if user_id:
            filters.append(Message.user_id == user_id)
        if user_name:
            filters.append(User.name.ilike(f"%{user_name}%"))

        result = await self.db.execute(
            select(Message)
            .join(User, Message.user_id == User.id)
            .options(joinedload(Message.sender))
            .filter(and_(*filters))
            .order_by(desc(Message.created_at))
        )
        return list(result.unique().scalars().all())

    async def find_or_create(
            self,
            message_id: str,
            sender_id: int,
            content: str,
            created_at: datetime,
            group_id: int = None
    ) -> Message:
        message = await self.find_by_message_id(message_id)

        if message:
            update_data = {}
            if content and message.content != content:
                update_data["content"] = content

            if update_data:
                return await self.update(message.id, update_data)
            return message

        new_message = Message(
            message_id=message_id,
            user_id=sender_id,
            group_id=group_id,
            content=content if content else None,
            created_at=created_at
        )
        return await self.insert(new_message)

    async def set_is_favorite(
            self,
            message_id: str,
    ) -> Optional[Message]:
        message = await self.find_by_message_id(message_id)

        if message:
            update_data = {"is_favorite": True}
            return await self.update(message.id, update_data)

        return None

    async def soft_delete(self, message_id: str) -> bool:
        message = await self.find_by_message_id(message_id)
        if not message:
            return False

        return await self.update(message.id, {"deleted_at": datetime.now()}) is not None

    async def count_by_group(self, group_id: int) -> int:
        from sqlalchemy import func as sql_func
        result = await self.db.execute(
            select(sql_func.count(Message.id))
            .filter(
                and_(
                    Message.group_id == group_id,
                    Message.deleted_at.is_(None)
                )
            )
        )
        return result.scalar_one()