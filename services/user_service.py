from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create(self, user_id: int, username: str | None, first_name: str | None) -> User:
        user = await self.session.get(User, user_id)
        if user:
            user.username = username
            user.first_name = first_name
            await self.session.commit()
            return user

        user = User(id=user_id, username=username, first_name=first_name, plan="basic", is_active=False)
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def get(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def list_active_users(self) -> list[User]:
        result = await self.session.execute(select(User).where(User.is_active.is_(True)))
        return list(result.scalars().all())
