from __future__ import annotations

import asyncio
import dataclasses
import functools
import typing

from vkquick.chatbot.exceptions import StopStateHandling
from vkquick.chatbot.wrappers.message import (
    CallbackButtonPressedMessage,
    Message,
    SentMessage,
)
from vkquick.chatbot.wrappers.page import Group, Page, User

if typing.TYPE_CHECKING:  # pragma: no cover
    from vkquick.base.event import BaseEvent
    from vkquick.base.event_factories import BaseEventFactory
    from vkquick.chatbot.application import App, Bot
    from vkquick.chatbot.wrappers.attachment import Document, Photo
    from vkquick.chatbot.package import Package

    SenderTypevar = typing.TypeVar("SenderTypevar", bound=Page)


NewEventPayloadFieldTypevar = typing.TypeVar("NewEventPayloadFieldTypevar")
BotPayloadFieldTypevar = typing.TypeVar("BotPayloadFieldTypevar")
AppPayloadFieldTypevar = typing.TypeVar("AppPayloadFieldTypevar")


@dataclasses.dataclass
class NewEvent(
    typing.Generic[
        AppPayloadFieldTypevar,
        BotPayloadFieldTypevar,
        NewEventPayloadFieldTypevar,
    ]
):
    event: BaseEvent
    bot: Bot[BotPayloadFieldTypevar, AppPayloadFieldTypevar]
    payload_factory: typing.Type[
        NewEventPayloadFieldTypevar
    ] = dataclasses.field(default=None)

    @classmethod
    async def from_event(
        cls,
        *,
        event: BaseEvent,
        bot: Bot,
    ):
        return cls(event=event, bot=bot)

    @functools.cached_property
    def payload(self) -> NewEventPayloadFieldTypevar:
        return self.payload_factory()

    @property
    def events_factory(self) -> BaseEventFactory:
        return self.bot.events_factory

    @property
    def app(self) -> App[AppPayloadFieldTypevar]:
        return self.bot.app


@dataclasses.dataclass
class NewMessage(
    NewEvent[
        NewEventPayloadFieldTypevar,
        BotPayloadFieldTypevar,
        AppPayloadFieldTypevar,
    ],
    SentMessage,
):
    @classmethod
    async def from_event(
        cls,
        *,
        event: BaseEvent,
        bot: Bot,
        payload_factory: typing.Optional[typing.Type[
            NewEventPayloadFieldTypevar
        ]] = None
    ):
        if event.type == 4:
            extended_message = await bot.api.method(
                "messages.get_by_id",
                message_ids=event.content[1],
            )
            extended_message = extended_message["items"][0]
            extended_message["text"] = extended_message["text"].replace(
                "<br>", "\n"
            )
        elif "message" in event.object:
            extended_message = event.object["message"]
        else:
            extended_message = event.object

        extended_message = Message(extended_message)

        return cls(
            event=event,
            bot=bot,
            api=bot.api,
            truncated_message=extended_message,
            payload_factory=payload_factory
        )

    @functools.cached_property
    def msg(self) -> Message:
        return typing.cast(Message, self.truncated_message)

    async def conquer_new_message(
        self, *, same_chat: bool = True, same_user: bool = True
    ) -> typing.AsyncGenerator[NewMessage, None]:
        async for new_event in self.bot.events_factory.listen():
            if new_event.type in {
                "message_new",
                "message_reply",
                4,
            }:
                conquered_message = await NewMessage.from_event(
                    event=new_event, bot=self.bot
                )
                if (
                    conquered_message.msg.peer_id == self.msg.peer_id
                    or not same_chat
                ) and (
                    conquered_message.msg.from_id == self.msg.from_id
                    or not same_user
                ):
                    yield conquered_message

    async def run_state_handling(
        self,
        app: App, /,
        payload: typing.Any = None
    ) -> typing.Any:
        # Цикличный импорт
        from vkquick.chatbot.application import Bot

        anonymous_bot = Bot(
            app=app,
            api=self.api,
            events_factory=self.events_factory,
            payload_factory=self.payload_factory
        )
        async for event in self.events_factory.listen():
            new_event_storage = NewEvent(event=event, bot=anonymous_bot, payload_factory=lambda: payload)
            try:
                await anonymous_bot.handle_event(new_event_storage, wrap_to_task=False)
            except StopStateHandling as err:
                return err.payload

    async def fetch_photos(self) -> typing.List[Photo]:
        return await self.msg.fetch_photos(self.api)

    async def fetch_docs(self) -> typing.List[Document]:
        return await self.msg.fetch_docs(self.api)

    async def download_photos(self) -> typing.List[bytes]:
        photos = await self.fetch_photos()
        download_coroutines = [
            photo.download_max_size(session=self.api.requests_session)
            for photo in photos
        ]
        downloaded_photos = await asyncio.gather(*download_coroutines)
        return downloaded_photos

    async def fetch_sender(
        self, typevar: typing.Type[SenderTypevar], /
    ) -> SenderTypevar:
        if self.msg.from_id > 0 and typevar in {Page, User}:
            return await User.fetch_one(self.api, self.msg.from_id)
        elif self.msg.from_id < 0 and typevar in {Page, Group}:
            return await Group.fetch_one(self.api, self.msg.from_id)
        else:
            raise ValueError(
                f"Can't make wrapper with typevar `{typevar}` and from_id `{self.msg.from_id}`"
            )

    def __repr__(self):
        return f"<vkquick.NewMessage text={self.msg.text!r}>"


class CallbackButtonPressed(NewEvent):
    @functools.cached_property
    def msg(self) -> CallbackButtonPressedMessage:
        return CallbackButtonPressedMessage(self.event.object)

    async def _call_action(self, **event_data):
        return await self.bot.api.method(
            "messages.send_message_event_answer",
            event_id=self.msg.event_id,
            user_id=self.msg.user_id,
            peer_id=self.msg.peer_id,
            event_data=event_data,
        )

    async def show_snackbar(self, text: str) -> dict:
        return await self._call_action(text=text, type="show_snackbar")

    async def open_link(self, link: str) -> dict:
        return await self._call_action(link=link, type="open_link")

    async def open_app(
        self, app_id: int, hash: str, owner_id: typing.Optional[int] = None
    ) -> dict:
        return await self._call_action(
            app_id=app_id, hash=hash, owner_id=owner_id, type="open_app"
        )
