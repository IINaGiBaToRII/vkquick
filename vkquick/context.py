from __future__ import annotations
import asyncio
import dataclasses
import typing as ty

from vkquick.wrappers.user import User
from vkquick.wrappers.message import Message
from vkquick.wrappers.attachment import Photo, Document
from vkquick.base.serializable import Attachment
from vkquick.events_generators.event import Event
from vkquick.utils import AttrDict, random_id as random_id_
from vkquick.base.handling_status import HandlingStatus
from vkquick.shared_box import SharedBox
from vkquick.api import API
from vkquick.uploaders import (
    upload_photos_to_message,
    upload_photo_to_message,
    upload_doc_to_message,
)
from vkquick.events_generators.longpoll import GroupLongPoll
from vkquick.keyboard import Keyboard
from vkquick.button import InitializedButton
from vkquick.carousel import Carousel, Element


@dataclasses.dataclass
class SentMessage:
    """
    Для ответов, содержащих поля peer_ids
    """

    peer_id: int
    message_id: int
    conversation_message_id: int
    api: API

    async def edit(
        self,
        message: ty.Optional[str] = None,
        /,
        *,
        lat: ty.Optional[float] = None,
        long: ty.Optional[float] = None,
        attachment: ty.Optional[ty.List[ty.Union[str, Attachment]]] = None,
        keep_forward_messages: ty.Optional[bool] = None,
        keep_snippets: ty.Optional[bool] = None,
        group_id: ty.Optional[int] = None,
        dont_parse_links: ty.Optional[bool] = None,
        template: ty.Optional[ty.Union[str, Carousel]] = None,
        keyboard: ty.Optional[ty.Union[str, Keyboard]] = None,
        **kwargs,
    ) -> ty.Any:
        real_params = locals().copy()
        del real_params["self"]
        kwargs = real_params.pop("kwargs")
        real_params.update(
            kwargs, peer_id=self.peer_id,
        )
        if self.message_id:
            real_params["message_id"] = self.message_id
        else:
            real_params[
                "conversation_message_id"
            ] = self.conversation_message_id
        return await self.api.method("messages.edit", real_params)

    async def delete(
        self,
        spam: ty.Optional[bool] = None,
        group_id: ty.Optional[int] = None,
        delete_for_all: bool = True,
        **kwargs,
    ) -> ty.Any:
        real_params = locals().copy()
        del real_params["self"]
        kwargs = real_params.pop("kwargs")
        real_params.update(
            kwargs, message_ids=self.message_id,
        )
        return await self.api.method("messages.delete", real_params)


@dataclasses.dataclass
class Context:

    shared_box: SharedBox
    event: Event
    filters_response: ty.Dict[str, HandlingStatus] = dataclasses.field(
        default_factory=dict
    )
    extra: AttrDict = dataclasses.field(default_factory=AttrDict)

    def __post_init__(self) -> None:
        self._attached_photos: ty.List[str, bytes] = []
        self._attached_docs: ty.List[dict] = []
        self._auto_set_content_source: bool = True
        self._attached_keyboard = None
        self._attached_carousel = None

    @property
    def msg(self) -> Message:
        return self.event.msg

    @property
    def api(self) -> API:
        """
        Текущий инстанс API, который был передан
        при инициализации бота
        """
        return self.shared_box.api

    def exclude_content_source(self) -> None:
        """
        После вызова этого метода автоматически
        сгенерированный `content_source` не добавится
        в `messages.send`
        """
        self._auto_set_content_source = False

    async def answer(
        self,
        message: ty.Optional[str] = None,
        /,
        *,
        random_id: ty.Optional[int] = None,
        lat: ty.Optional[float] = None,
        long: ty.Optional[float] = None,
        attachment: ty.Optional[ty.List[ty.Union[str, Attachment]]] = None,
        reply_to: ty.Optional[int] = None,
        forward_messages: ty.Optional[ty.List[int]] = None,
        sticker_id: ty.Optional[int] = None,
        group_id: ty.Optional[int] = None,
        keyboard: ty.Optional[ty.Union[str, Keyboard]] = None,
        payload: ty.Optional[str] = None,
        dont_parse_links: ty.Optional[bool] = None,
        disable_mentions: ty.Optional[bool] = None,
        intent: ty.Optional[str] = None,
        expire_ttl: ty.Optional[int] = None,
        silent: ty.Optional[bool] = None,
        subscribe_id: ty.Optional[int] = None,
        content_source: ty.Optional[str] = None,
        forward: ty.Optional[str] = None,
        **kwargs,
    ) -> SentMessage:
        """
        Отправляет сообщение в тот же диалог/беседу,
        откуда пришло. Все поля соответствуют
        методу `messages.send`
        """
        params = {"peer_ids": self.msg.peer_id}
        return await self._send_message_via_local_kwargs(locals(), params)

    async def reply(
        self,
        message: ty.Optional[str] = None,
        /,
        *,
        random_id: ty.Optional[int] = None,
        lat: ty.Optional[float] = None,
        long: ty.Optional[float] = None,
        attachment: ty.Optional[ty.List[ty.Union[str, Attachment]]] = None,
        sticker_id: ty.Optional[int] = None,
        group_id: ty.Optional[int] = None,
        keyboard: ty.Optional[ty.Union[str, Keyboard]] = None,
        payload: ty.Optional[str] = None,
        dont_parse_links: ty.Optional[bool] = None,
        disable_mentions: ty.Optional[bool] = None,
        intent: ty.Optional[str] = None,
        expire_ttl: ty.Optional[int] = None,
        silent: ty.Optional[bool] = None,
        subscribe_id: ty.Optional[int] = None,
        content_source: ty.Optional[str] = None,
        **kwargs,
    ) -> SentMessage:
        """
        Отвечает на сообщение, которым была вызвана команда.
        Все поля соответствуют методу `messages.send`
        """
        params = {
            "peer_ids": self.msg.peer_id,
        }
        if self.msg.id:
            params["reply_to"] = self.msg.id
        else:
            params["forward"] = {
                "is_reply": True,
                "conversation_message_ids": [
                    self.msg.conversation_message_id
                ],
                "peer_id": self.msg.peer_id,
            }
        return await self._send_message_via_local_kwargs(locals(), params)

    async def forward(
        self,
        message: ty.Optional[str] = None,
        /,
        *,
        random_id: ty.Optional[int] = None,
        lat: ty.Optional[float] = None,
        long: ty.Optional[float] = None,
        attachment: ty.Optional[ty.List[ty.Union[str, Attachment]]] = None,
        sticker_id: ty.Optional[int] = None,
        group_id: ty.Optional[int] = None,
        keyboard: ty.Optional[ty.Union[str, Keyboard]] = None,
        payload: ty.Optional[str] = None,
        dont_parse_links: ty.Optional[bool] = None,
        disable_mentions: ty.Optional[bool] = None,
        intent: ty.Optional[str] = None,
        expire_ttl: ty.Optional[int] = None,
        silent: ty.Optional[bool] = None,
        subscribe_id: ty.Optional[int] = None,
        content_source: ty.Optional[str] = None,
        **kwargs,
    ) -> SentMessage:
        """
        Пересылает сообщение, которым была вызвана команда.
        Все поля соответствуют методу `messages.send`
        """
        params = {
            "peer_ids": self.msg.peer_id,
        }
        if self.msg.id:
            params["forward_messages"] = self.msg.id
        else:
            params["forward"] = {
                "conversation_message_ids": [
                    self.msg.conversation_message_id
                ],
                "peer_id": self.msg.peer_id,
            }
        return await self._send_message_via_local_kwargs(locals(), params)

    async def fetch_replied_message_sender(
        self,
        fields: ty.Optional[ty.List[str]] = None,
        name_case: ty.Optional[str] = None,
    ) -> ty.Optional[User]:
        """
        Возвращает специальную обертку на пользователя
        из replied-сообщения. Если такого нет, то вернется None.
        Получение пользователя использует кэширование.
        Аргументы этой функции будут переданы в `users.get`
        """
        if self.msg.reply_message is None:
            return None

        user_id = self.msg.reply_message.from_id
        user = await self.api.fetch_user_via_id(
            user_id, fields=fields, name_case=name_case
        )
        return user

    async def fetch_forward_messages_sender(
        self,
        fields: ty.Optional[ty.List[str]] = None,
        name_case: ty.Optional[str] = None,
    ) -> ty.List[User]:
        """
        Возвращает список людей из пересланных
        сообщений специальными обертками.
        Если таких нет, то вернется пустой список.
        Получение пользователя использует кэширование.
        Аргументы этой функции будут переданы в `users.get`
        на каждого пользователя
        """
        user_ids = [message.from_id for message in self.msg.fwd_messages]
        users = await self.api.fetch_users_via_ids(
            user_ids, fields=fields, name_case=name_case
        )
        return users

    async def fetch_attached_user(
        self,
        fields: ty.Optional[ty.List[str]] = None,
        name_case: ty.Optional[str] = None,
    ) -> ty.Optional[User]:
        """
       Возвращает обертку на "прикрепленного пользователя".
       Если есть replied-сообщение -- вернется отправитель того сообщения,
       если есть пересланное сообщение -- отправитель первого прикрепленного сообщения.
       Если ни того, ни другого нет, вернется `None`.
       Получение пользователя использует кэширование.
       Аргументы этой функции будут переданы в `users.get`
       """
        replied_user = await self.fetch_replied_message_sender(
            fields=fields, name_case=name_case
        )
        if replied_user is not None:
            return replied_user
        if not self.msg.fwd_messages:
            return None
        first_user_from_fwd = await self.api.fetch_user_via_id(
            self.msg.fwd_messages[0].from_id,
            fields=fields,
            name_case=name_case,
        )
        return first_user_from_fwd

    async def fetch_sender(
        self,
        fields: ty.Optional[ty.List[str]] = None,
        name_case: ty.Optional[str] = None,
    ) -> User:
        """
        Специальной оберткой возвращает пользователя,
        который отправил сообщение.
        Получение пользователя использует кэширование.
        Аргументы этой функции будут переданы в `users.get`
        """
        sender = await self.api.fetch_user_via_id(
            self.msg.from_id, fields=fields, name_case=name_case
        )
        return sender

    def attach_keyboard(
        self,
        *buttons: ty.Union[InitializedButton, type(Ellipsis)],
        one_time: bool = True,
        inline: bool = False,
    ) -> None:
        self._attached_keyboard = Keyboard(one_time=one_time, inline=inline)
        self._attached_keyboard.build(*buttons)

    def fetch_photos(self) -> ty.List[Photo]:
        """
        Возвращает только фотографии из всего,
        что есть во вложениях, оборачивая их в обертку
        """
        photos = [
            Photo(attachment.photo)
            for attachment in self.msg.attachments
            if attachment.type == "photo"
        ]
        return photos

    def fetch_docs(self):
        """
        Возвращает только вложения с типом документ из всего,
        что есть во вложениях, оборачивая их в обертку
        """
        docs = [
            Document(getattr(attachment, attachment.type))
            for attachment in self.msg.attachments
            if attachment.type == "doc"
        ]
        return docs

    def attach_photos(self, *photos: ty.Union[bytes, str]) -> None:
        """
        Позволяет добавить фотографию к следующему сообщению,
        которое будет отправлено
        """
        self._attached_photos.extend(photos)

    def attach_doc(
        self,
        *,
        content: ty.Optional[ty.Union[str, bytes]] = None,
        filename: ty.Optional[str] = None,
        filepath: ty.Optional[str] = None,
        tags: ty.Optional[str] = None,
        return_tags: ty.Optional[bool] = None,
        type_: ty.Optional[
            ty.Literal["doc", "audio_message", "graffiti"]
        ] = None,
    ) -> None:
        baked_params = locals().copy()
        del baked_params["self"]
        self._attached_docs.append(baked_params)

    def attach_carousel(self, *elements: Element) -> None:
        carousel = Carousel.build(*elements)
        self._attached_carousel = carousel

    async def upload_photos(
        self, *photos: ty.Union[bytes, str]
    ) -> ty.List[Photo]:
        return await upload_photos_to_message(
            *photos, api=self.api, peer_id=self.msg.peer_id
        )

    async def upload_photo(self, photo: ty.Union[bytes, str]) -> Photo:
        return await upload_photo_to_message(
            photo, api=self.api, peer_id=self.msg.peer_id
        )

    async def upload_doc(
        self,
        *,
        content: ty.Optional[ty.Union[str, bytes]] = None,
        filename: ty.Optional[str] = None,
        filepath: ty.Optional[str] = None,
        tags: ty.Optional[str] = None,
        return_tags: ty.Optional[bool] = None,
        type_: ty.Optional[
            ty.Literal["doc", "audio_message", "graffiti"]
        ] = None,
    ) -> Document:
        baked_params = locals().copy()
        del baked_params["self"]
        return await upload_doc_to_message(
            **baked_params, api=self.api, peer_id=self.msg.peer_id
        )

    async def edit(
        self,
        message: ty.Optional[str] = None,
        /,
        *,
        lat: ty.Optional[float] = None,
        long: ty.Optional[float] = None,
        attachment: ty.Optional[ty.List[ty.Union[str, Attachment]]] = None,
        keep_forward_messages: ty.Optional[bool] = None,
        keep_snippets: ty.Optional[bool] = None,
        group_id: ty.Optional[int] = None,
        dont_parse_links: ty.Optional[bool] = None,
        template: ty.Optional[ty.Union[str, Carousel]] = None,
        keyboard: ty.Optional[ty.Union[str, Keyboard]] = None,
        **kwargs,
    ) -> ty.Any:
        if not self.msg.out:
            raise Exception("Can't edit message if it isn't yours")
        mock_message = SentMessage(
            message_id=self.msg.id,
            peer_id=self.msg.peer_id,
            conversation_message_id=self.msg.cmid,
            api=self.api,
        )
        return await mock_message.edit(
            message,
            lat=lat,
            long=long,
            attachment=attachment,
            keep_forward_messages=keep_forward_messages,
            keep_snippets=keep_snippets,
            dont_parse_links=dont_parse_links,
            group_id=group_id,
            template=template,
            keyboard=keyboard,
            **kwargs,
        )

    async def delete(
        self,
        spam: ty.Optional[bool] = None,
        group_id: ty.Optional[int] = None,
        delete_for_all: bool = True,
        **kwargs,
    ) -> ty.Any:
        mock_message = SentMessage(
            message_id=self.msg.id,
            peer_id=self.msg.peer_id,
            conversation_message_id=self.msg.cmid,
            api=self.api,
        )
        return await mock_message.delete(
            spam=spam,
            group_id=group_id,
            delete_for_all=delete_for_all,
            **kwargs,
        )

    def __str__(self) -> str:
        return (
            f"{self.__class__.__name__}"
            f"(event, filters_response, extra, shared_box)"
        )

    async def _send_message_via_local_kwargs(
        self, local_kwargs: dict, pre_params: dict
    ) -> SentMessage:
        """
        Вспомогательная функция для методов,
        реализующих отправку сообщений (reply. answer).
        Фильтрует аргументы, которые были переданы при вызове этого метода
        """
        for name, value in local_kwargs.items():
            if name == "kwargs":
                pre_params.update(value)
            elif name != "self" and value is not None:
                pre_params.update({name: value})

        del pre_params["params"]

        if local_kwargs["random_id"] is None:
            pre_params["random_id"] = random_id_()

        if "attachment" not in pre_params and (
            self._attached_photos or self._attached_docs
        ):
            photos_uploading_task = None
            docs_uploading_tasks = []
            if self._attached_photos:
                photos_uploading_task = self.upload_photos(
                    *self._attached_photos
                )

            if self._attached_docs:
                docs_uploading_tasks = [
                    self.upload_doc(**params)
                    for params in self._attached_docs
                ]
            if photos_uploading_task is not None:
                photo_attachments, *docs_attachments = await asyncio.gather(
                    photos_uploading_task, *docs_uploading_tasks
                )
                photo_attachments.extend(docs_attachments)
                pre_params["attachment"] = photo_attachments
            else:
                pre_params["attachment"] = await asyncio.gather(
                    *docs_uploading_tasks
                )
        if (
            self._auto_set_content_source
            and "content_source" not in pre_params
            and isinstance(self.shared_box.events_generator, GroupLongPoll)
        ):
            pre_params["content_source"] = {
                "type": "message",
                "owner_id": -self.shared_box.events_generator.group_id,
                "peer_id": self.msg.peer_id,
                "conversation_message_id": self.msg.conversation_message_id,
            }
        if self._attached_keyboard is not None:
            if "keyboard" in pre_params:
                raise ValueError(
                    "Unexpected passed keyboard. "
                    "You already attached a keyboard "
                    "before via `attach_keyboard`"
                )
        if self._attached_carousel is not None:
            if "template" in pre_params:
                raise ValueError(
                    "Unexpected passed keyboard. "
                    "You already attached a keyboard "
                    "before via `attach_keyboard`"
                )
            pre_params["template"] = self._attached_carousel

        response = await self.api.method("messages.send", pre_params)
        response = SentMessage(**response[0](), api=self.api)
        return response
