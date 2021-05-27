from __future__ import annotations

import dataclasses
import typing as ty

from vkquick.chatbot.base.filter import BaseFilter
from vkquick.chatbot.exceptions import FilterFailedError

if ty.TYPE_CHECKING:
    from vkquick.chatbot.storages import NewMessage


class OnlyMe(BaseFilter):
    async def make_decision(self, ctx: NewMessage):
        if not ctx.msg.out:
            raise FilterFailedError()


class IgnoreBots(BaseFilter):
    async def make_decision(self, ctx: NewMessage):
        if ctx.msg.from_id < 0:
            raise FilterFailedError()


@dataclasses.dataclass
class Dynamic(BaseFilter):
    executable: ty.Callable[[NewMessage], ...]

    async def make_decision(self, ctx: NewMessage):
        if not self.executable(ctx):
            raise FilterFailedError()
