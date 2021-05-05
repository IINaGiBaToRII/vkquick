from __future__ import annotations

import dataclasses
import datetime
import typing as ty

from vkquick import API
from vkquick.cached_property import cached_property
from vkquick.ext.chatbot.base.wrapper import Wrapper
from vkquick.ext.chatbot.ui_builders.keyboard import Keyboard
from vkquick.ext.chatbot.utils import peer
from vkquick.ext.chatbot.wrappers.attachment import Document, Photo
from vkquick.ext.chatbot.utils import random_id as random_id_
from vkquick.json_parsers import json_parser_policy


class TruncatedMessage(Wrapper):
    @property
    def id(self) -> int:
        return self.fields["message_id"]

    @property
    def peer_id(self) -> int:
        return self.fields["peer_id"]

    @property
    def conversation_message_id(self) -> int:
        return self.fields["conversation_message_id"]

    # Shortcuts
    @property
    def cmid(self) -> int:
        return self.conversation_message_id


class Message(TruncatedMessage):
    @property
    def id(self) -> int:
        return self.fields["id"]

    @cached_property
    def chat_id(self) -> int:
        chat_id = self.peer_id - peer()
        if chat_id < 0:
            raise ValueError(
                "Can't get `chat_id` if message " "wasn't sent in a chat"
            )

        return chat_id

    @cached_property
    def date(self) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(self.fields["date"])

    @property
    def from_id(self) -> int:
        return self.fields["from_id"]

    @property
    def text(self) -> str:
        return self.fields["text"]

    @property
    def random_id(self) -> int:
        return self.fields["random_id"]

    @property
    def attachments(self) -> ty.List[dict]:
        return self.fields["attachments"]

    @property
    def important(self) -> bool:
        return bool(self.fields["important"])

    @property
    def is_hidden(self) -> bool:
        return bool(self.fields["is_hidden"])

    @property
    def out(self) -> bool:
        return bool(self.fields["out"])

    @cached_property
    def keyboard(self) -> ty.Optional[dict]:
        if "keyboard" in self.fields:
            return json_parser_policy.loads(self.fields["keyboard"])
        return None

    @cached_property
    def fwd_messages(self) -> ty.List[Message]:
        return list(map(self.__class__, self.fields["fwd_messages"]))

    @property
    def geo(self) -> ty.Optional[dict]:
        return self.fields.get("geo")

    @cached_property
    def payload(self) -> ty.Optional[dict]:
        if "payload" in self.fields:
            return json_parser_policy.loads(self.fields["payload"])
        return None

    @cached_property
    def reply_message(self) -> ty.Optional[Message]:
        if "reply_message" in self.fields:
            return self.__class__(self.fields["reply_message"])
        return None

    @property
    def action(self) -> dict:
        return self.fields.get("action")

    @property
    def ref(self) -> ty.Optional[str]:
        return self.fields.get("ref")

    @property
    def ref_source(self) -> ty.Optional[str]:
        return self.fields.get("ref_source")

    @property
    def expire_ttl(self) -> ty.Optional[int]:
        return self.fields.get("expire_ttl")

    @cached_property
    def photos(self) -> ty.List[Photo]:
        """
        Возвращает только фотографии из всего,
        что есть во вложениях, оборачивая их в обертку
        """
        photos = [
            Photo(attachment["photo"])
            for attachment in self.attachments
            if attachment["type"] == "photo"
        ]
        return photos

    @cached_property
    def docs(self) -> ty.List[Document]:
        """
        Возвращает только вложения с типом документ из всего,
        что есть во вложениях, оборачивая их в обертку
        """
        docs = [
            Document(attachment["doc"])
            for attachment in self.attachments
            if attachment["type"] == "doc"
        ]
        return docs


@dataclasses.dataclass
class SentMessage:
    api: API
    message: TruncatedMessage

    async def _send_message(self, params: dict) -> TruncatedMessage:
        sent_message = await self.api.method("messages.send", **params)
        return TruncatedMessage(sent_message)

    async def reply(
            self,
            message: ty.Optional[str] = None,
            *,
            random_id: ty.Optional[int] = None,
            lat: ty.Optional[float] = None,
            long: ty.Optional[float] = None,
            attachment: ty.Optional[ty.List[ty.Union[str]]] = None,
            sticker_id: ty.Optional[int] = None,
            group_id: ty.Optional[int] = None,
            keyboard: ty.Optional[ty.Union[str, Keyboard]] = None,
            payload: ty.Optional[str] = None,
            dont_parse_links: ty.Optional[bool] = None,
            disable_mentions: bool = True,
            intent: ty.Optional[str] = None,
            expire_ttl: ty.Optional[int] = None,
            silent: ty.Optional[bool] = None,
            subscribe_id: ty.Optional[int] = None,
            content_source: ty.Optional[str] = None,
            **kwargs,
    ) -> TruncatedMessage:
        params = dict(
            message=message,
            random_id=random_id_() if random_id is None else random_id,
            lat=lat,
            long=long,
            attachment=attachment,
            sticker_id=sticker_id,
            group_id=group_id,
            keyboard=keyboard,
            payload=payload,
            dont_parse_links=dont_parse_links,
            disable_mentions=disable_mentions,
            intent=intent,
            expire_ttl=expire_ttl,
            silent=silent,
            subscribe_id=subscribe_id,
            content_source=content_source,
            peer_ids=self.message.peer_id,
            **kwargs,
        )
        if self.message.id:
            params["reply_to"] = self.message.id
        else:
            params["forward"] = {
                "is_reply": True,
                "conversation_message_ids": [
                    self.message.conversation_message_id
                ],
                "peer_id": self.message.peer_id,
            }
        return await self._send_message(params)

    async def answer(
            self,
            message: ty.Optional[str] = None,
            *,
            random_id: ty.Optional[int] = None,
            lat: ty.Optional[float] = None,
            long: ty.Optional[float] = None,
            attachment: ty.Optional[ty.List[ty.Union[str]]] = None,
            sticker_id: ty.Optional[int] = None,
            group_id: ty.Optional[int] = None,
            keyboard: ty.Optional[ty.Union[str, Keyboard]] = None,
            payload: ty.Optional[str] = None,
            dont_parse_links: ty.Optional[bool] = None,
            disable_mentions: bool = True,
            intent: ty.Optional[str] = None,
            expire_ttl: ty.Optional[int] = None,
            silent: ty.Optional[bool] = None,
            subscribe_id: ty.Optional[int] = None,
            content_source: ty.Optional[str] = None,
            **kwargs,
    ) -> TruncatedMessage:
        params = dict(
            message=message,
            random_id=random_id_() if random_id is None else random_id,
            lat=lat,
            long=long,
            attachment=attachment,
            sticker_id=sticker_id,
            group_id=group_id,
            keyboard=keyboard,
            payload=payload,
            dont_parse_links=dont_parse_links,
            disable_mentions=disable_mentions,
            intent=intent,
            expire_ttl=expire_ttl,
            silent=silent,
            subscribe_id=subscribe_id,
            content_source=content_source,
            peer_ids=self.message.peer_id,
            **kwargs,
        )
        return await self._send_message(params)

    async def forward(
            self,
            message: ty.Optional[str] = None,
            *,
            random_id: ty.Optional[int] = None,
            lat: ty.Optional[float] = None,
            long: ty.Optional[float] = None,
            attachment: ty.Optional[ty.List[ty.Union[str]]] = None,
            sticker_id: ty.Optional[int] = None,
            group_id: ty.Optional[int] = None,
            keyboard: ty.Optional[ty.Union[str, Keyboard]] = None,
            payload: ty.Optional[str] = None,
            dont_parse_links: ty.Optional[bool] = None,
            disable_mentions: bool = True,
            intent: ty.Optional[str] = None,
            expire_ttl: ty.Optional[int] = None,
            silent: ty.Optional[bool] = None,
            subscribe_id: ty.Optional[int] = None,
            content_source: ty.Optional[str] = None,
            **kwargs,
    ) -> TruncatedMessage:
        params = dict(
            message=message,
            random_id=random_id_() if random_id is None else random_id,
            lat=lat,
            long=long,
            attachment=attachment,
            sticker_id=sticker_id,
            group_id=group_id,
            keyboard=keyboard,
            payload=payload,
            dont_parse_links=dont_parse_links,
            disable_mentions=disable_mentions,
            intent=intent,
            expire_ttl=expire_ttl,
            silent=silent,
            subscribe_id=subscribe_id,
            content_source=content_source,
            peer_ids=self.message.peer_id,
            **kwargs,
        )
        if self.message.id:
            params["forward_messages"] = self.message.id
        else:
            params["forward"] = {
                "conversation_message_ids": [
                    self.message.conversation_message_id
                ],
                "peer_id": self.message.peer_id,
            }
        return await self._send_message(params)