from __future__ import annotations

import asyncio
import datetime
import enum
import io
import os
import re
import typing
import urllib.parse

import aiofiles
import cachetools
import reqsnaked
from loguru import logger

from vkquick.base.api_serializable import APISerializableMixin
from vkquick.base.session_container import SessionContainerMixin
from vkquick.captcha.captcha_handler import captcha_handler
from vkquick.chatbot.utils import download_file
from vkquick.chatbot.wrappers.attachment import Document, Photo, VideoMessage, Video, Audio
from vkquick.chatbot.wrappers.page import Group, Page, User
from vkquick.exceptions import APIError
from vkquick.json_parsers import json_parser_policy
from vkquick.logger import format_mapping


if typing.TYPE_CHECKING:  # pragma: no cover
    from vkquick.base.json_parser import BaseJSONParser

    PhotoEntityTyping = typing.Union[str, bytes, typing.BinaryIO, os.PathLike]


@enum.unique
class TokenOwner(enum.Enum):
    """
    Тип владельца токена: пользователь/группа/не определено
    """

    USER = enum.auto()
    GROUP = enum.auto()
    UNKNOWN = enum.auto()


class Semaphore:

    def __init__(self, access_times: int, per_period: datetime.timedelta):
        self.access_times = access_times
        self.per_period = per_period

        self.boundary: datetime.datetime = datetime.datetime.now()
        self.current_block_access = 0
        self.benchmark_stamp = lambda: datetime.datetime.now()

    def calc_delay(self) -> float:
        stamp = self.benchmark_stamp()
        if stamp >= self.boundary:
            self.current_block_access += 1

            if self.current_block_access == self.access_times:
                self.boundary = stamp + self.per_period
                self.current_block_access = 0
            return 0

        self.current_block_access += 1

        delay = self.boundary - stamp
        if self.current_block_access == self.access_times:
            self.boundary += self.per_period
            self.current_block_access = 0

        return delay.total_seconds()


class API(SessionContainerMixin):
    def __init__(
        self,
        token: str,
        token_owner: TokenOwner = TokenOwner.UNKNOWN,
        version: str = "5.135",
        requests_url: str = "https://api.vk.com/method/",
        requests_session: typing.Optional[reqsnaked.Client] = None,
        json_parser: typing.Optional[BaseJSONParser] = None,
        cache_table: typing.Optional[cachetools.Cache] = None,
        proxies: typing.Optional[typing.List[str]] = None,
    ):
        SessionContainerMixin.__init__(
            self, requests_session=requests_session, json_parser=json_parser
        )
        if token.startswith("$"):
            self._token = os.environ[token[1:]]
        else:
            self._token = token
        self._version = version
        self._token_owner = token_owner
        self._owner_schema = None
        self._requests_url = requests_url
        self._proxies = proxies
        self._cache_table = cache_table or cachetools.TTLCache(
            ttl=7200, maxsize=2 ** 12
        )
        self.semaphore = Semaphore(
            access_times=1,
            per_period=datetime.timedelta(seconds=1 / 20 if token_owner is TokenOwner.GROUP else 1 / 3)
        )
        self._method_name = ""
        self._use_cache = False
        self._stable_request_params = {"v": self._version}

    def use_cache(self) -> API:
        """
        Включает кэширование для следующего запроса.
        Кэширование выключается автоматически, т.е.
        кэширование будет использовано только для первого следующего
        выполняемого API запроса.

        Включение кэширования подразумевает, что следующий запрос
        будет занесен в специальную кэш-таблицу. Ключ кэша
        привязывается к имени вызываемого метода и переданным параметрам,
        а значение -- к ответу API. Если запрос с таким именем метода
        и такими параметрами уже был выполнен когда-то, то вместо
        отправки запроса будет возвращено значение из кэш-таблицы

        Если необходимо передать свою собственную имплементацию
        кэш-таблицы, укажите соответствующий инстанс при инициализации объекта
        в поле `cache_table`. По умолчанию используется TTL-алгоритм.

        Returns:
            Тот же самый инстанс API, готовый к кэшированному запросу
        """
        self._use_cache = True
        return self

    async def define_token_owner(self) -> typing.Tuple[TokenOwner, Page]:
        """
        Позволяет определить владельца токена: группа или пользователь.

        Метод использует кэширование, поэтому в своем коде
        можно смело каждый раз вызывать этот метод, не боясь лишних
        исполняемых запросов

        Владелец токена будет определен автоматически после первого выполненного
        запроса для определения задержки, если `token_owner` поле
        не было установленно вручную при инициализации объекта

        Returns:
            Возвращает словарь, первый элемент которого TokenOwner значение,
            указывающее, группа это или пользователь, а в второй -- сама схема объекта
            сущности пользователя/группы, обернутая соответствующим враппером
        :rtype:
        """
        if (
            self._token_owner != TokenOwner.UNKNOWN
            and self._owner_schema is not None
        ):
            return self._token_owner, self._owner_schema
        owner_schema = await self.use_cache().method("users.get")
        if owner_schema:
            self._owner_schema = User(owner_schema[0].parse())
            self._token_owner = TokenOwner.USER
        else:
            owner_schema = await self.use_cache().method("groups.get_by_id")
            self._owner_schema = Group(owner_schema[0].parse())
            self._token_owner = TokenOwner.GROUP
        return self._token_owner, self._owner_schema

    def __getattr__(self, attribute: str) -> API:
        """
        Используя `__getattr__`, класс предоставляет возможность
        вызывать методы API, как будто бы обращаясь к атрибутам.

        Arguments:
            attribute: Имя/заголовок названия метода
        Returns:
            Собственный инстанс класса для того,
            чтобы была возможность продолжить выстроить имя метода через точку
        """
        if self._method_name:
            self._method_name += f".{attribute}"
        else:
            self._method_name = attribute
        return self

    async def __call__(
        self,
        **request_params,
    ) -> typing.Any:
        """
        Вызывает метод `method` после обращения к имени метода через `__getattr__`

        Arguments:
            request_params: Параметры, принимаемые методом, которые описаны в документации API

        Returns:
            Пришедший от API ответ
        """
        method_name = self._method_name
        self._method_name = ""
        return await self.method(method_name, **request_params)

    async def method(self, method_name: str, **request_params) -> typing.Any:
        """
        Выполняет необходимый API запрос с нужным методом и параметрами.
        Вызов метода поддерживает конвертацию из snake_case в camelCase.

        Перед вызовом этого метода может быть вызван `.use_cache()` для
        включения возможности кэш-логики запроса

        Каждый передаваемый параметр проходит специальный этап конвертации перед
        передачей в запрос по следующему принципу:

        * Все элементы списков, кортежей и множеств проходят конвертацию рекурсивно и
            объединяются в строку через `,`
        * Все словари автоматически дампятся в JSON-строку установленным JSON-парсером
        * Все True/False значения становятся 1 и 0 соответственно (требуется для reqsnaked)
        * Если переданный объект имплементирует класс `APISerializableMixin`,
            вызывается соответствующий метод класса для конвертации в желаемое
            значение

        К параметрам автоматически добавляются `access_token` (ключ доступа) и `v` (версия API),
        переданные при инициализации, но каждый из этих полей может быть задан вручную для
        конкретного запроса. Например, необходимо вызвать метод с другой версией API
        или передать другой токен.


        Arguments:
            method_name: Имя вызываемого метода API
            request_params: Параметры, принимаемые методом, которые описаны в документации API.

        Returns:
            Пришедший от API ответ.

        Raises:
            VKAPIError: В случае ошибки, пришедшей от некорректного вызова запроса.
        """
        use_cache = self._use_cache
        self._use_cache = False

        captcha_sid = None
        captcha_key = None
        while True:

            try:
                request_params.update({"captcha_sid": captcha_sid, "captcha_key": captcha_key})
                return await self._make_api_request(
                    method_name=method_name,
                    request_params=request_params,
                    use_cache=use_cache,
                )
            except APIError[14] as err:
                captcha_sid = err.extra_fields["captcha_sid"]
                captcha_key = await captcha_handler(err.extra_fields["captcha_img"])

    async def execute(
        self, *code: typing.Union[str, CallMethod]
    ) -> typing.Any:
        """
        Исполняет API метод `execute` с переданным VKScript-кодом.

        Arguments:
            code: VKScript код

        Returns:
            Пришедший ответ от API

        Raises:
            VKAPIError: В случае ошибки, пришедшей от некорректного вызова запроса.
        """
        if not isinstance(code[0], str):
            code = "return [{}];".format(
                ", ".join(call.to_execute() for call in code)
            )
        return await self.method("execute", code=code)

    async def _make_api_request(
        self,
        method_name: str,
        request_params: typing.Dict[str, typing.Any],
        use_cache: bool,
    ) -> typing.Any:
        """
        Выполняет API запрос на определенный метод с заданными параметрами

        Arguments:
            method_name: Имя метода API
            request_params: Параметры, переданные для метода
            use_cache: Использовать кэширование

        Raises:
            VKAPIError: В случае ошибки, пришедшей от некорректного вызова запроса.
        """
        # Конвертация параметров запроса под особенности API и имени метода
        real_method_name = _convert_method_name(method_name)
        real_request_params = _convert_params_for_api(request_params)
        extra_request_params = self._stable_request_params.copy()
        extra_request_params.update(real_request_params)

        # Определение владельца токена нужно
        # для определения задержки между запросами
        if self._token_owner is None:
            await self.fetch_token_owner_entity()

        # Кэширование запросов по их методу и переданным параметрам
        # `cache_hash` -- ключ кэш-таблицы
        if use_cache:
            cache_hash = urllib.parse.urlencode(real_request_params)
            cache_hash = f"{method_name}#{cache_hash}"
            if cache_hash in self._cache_table:
                return self._cache_table[cache_hash]

        # Отправка запроса с последующей проверкой ответа
        response = await self._send_api_request(
            real_method_name, extra_request_params
        )
        logger.opt(colors=True).info(
            **format_mapping(
                "Called method <m>{method_name}</m>({params})",
                "<c>{key}</c>=<y>{value!r}</y>",
                real_request_params,
            ),
            method_name=real_method_name,
        )
        # logger.opt(lazy=True).debug(
        #     "Response is: {response}", response=lambda: pretty_view(response)
        # )

        # Обработка ошибки вызова запроса
        if "error" in response:
            error = response["error"].parse().copy()
            exception_class = APIError[error["error_code"]][0]
            status_code = error.pop("error_code")
            raise exception_class(
                status_code=status_code,  # noqa
                description=error.pop("error_msg"),  # noqa
                request_params=error.pop("request_params"),  # noqa
                extra_fields=error,  # noqa
            )
        else:
            response = response["response"]
            response.base_path = "response"

        # Если кэширование включено -- запрос добавится в таблицу
        if use_cache:
            self._cache_table[cache_hash] = response  # noqa

        return response

    async def _send_api_request(self, method_name: str, params: dict):
        """
        Выполняет сам API запрос с готовыми параметрами и именем метода

        Arguments:
            method_name: Имя метода
            params: Словарь параметров

        Returns:
            Сырой ответ от API
        """

        request = reqsnaked.Request(
            "POST", url=self._requests_url + method_name, form=params, bearer_auth=self._token
        )
        await asyncio.sleep(self.semaphore.calc_delay())
        response = await self.requests_session.send(request)
        return await self.parse_json_body(response)

    async def _fetch_photo_entity(self, photo: PhotoEntityTyping) -> bytes:
        """
        Получает байты фотографии через IO-хранилища/ссылку/путь до файла
        """
        if isinstance(photo, bytes):
            return photo
        elif isinstance(photo, io.BytesIO):
            return photo.getvalue()
        elif isinstance(photo, str) and photo.startswith("http"):
            return await download_file(photo, session=await self.requests_session)
        elif isinstance(photo, (str, os.PathLike)):
            async with aiofiles.open(photo, "rb") as file:
                return await file.read()
        else:
            raise TypeError(
                "Can't recognize photo entity. "
                "Accept only bytes, BytesIO, "
                "URL-like string and Path-like object or string"
            )

    async def upload_audio(
        self,
        content: typing.Union[str, bytes],
        title: str = None,
        artist: str = None,
    ) -> Audio:
        """
        Сохраняет аудиозапись.
        Arguments:
            content: Содержимое файла аудиозаписи.
            title: Название композиции.
            artist: Автор композиции.
        Returns:
            None
        """
        data_storage = reqsnaked.Multipart(
            reqsnaked.Part(
                "file", content,
                mime="audio/mp3",
                filename="file.mp3"
            )
        )

        uploading_info = await self.method("audio.get_upload_server")

        request = reqsnaked.Request(
            "POST", url=uploading_info["upload_url"].parse(), multipart=data_storage
        )
        response = await self.requests_session.send(request)
        response = await self.parse_json_body(response)
        fields = await self.method(
            "audio.save",
            **response.unpack(),
            artist=artist,
            title=title,
        )
        return Audio(fields)

    async def upload_photos_to_message(
        self, *photos: PhotoEntityTyping, peer_id: int = 0
    ) -> typing.List[Photo]:
        """
        Загружает фотографию в сообщения

        Arguments:
            photos: Фотографии в виде ссылки/пути до файла/сырых байтов/
                IO-хранилища/Path-like объекта
            peer_id: ID диалога или беседы, куда загружаются фотографии. Если
                не передавать, то фотографии загрузятся в скрытый альбом. Рекомендуется
                исключительно для тестирования, т.к. такой альбом имеет лимиты
        Returns:
            Список врапперов загруженных фотографий, который можно напрямую
            передать в поле `attachment` при отправке сообщения
        """
        photo_bytes_coroutines = [
            self._fetch_photo_entity(photo) for photo in photos
        ]
        photo_bytes = await asyncio.gather(*photo_bytes_coroutines)
        uploading_info = await self.method(
            "photos.get_messages_upload_server", peer_id=peer_id
        )
        result_photos = []
        upload_to_messages = [
            self._upload_photo(
                upload_url=uploading_info["upload_url"].parse(),
                photo_bytes=chunk,
                result_photos=result_photos,
                destination="messages"
            ) for chunk in divide_chunks(photo_bytes, 5)
        ]
        await asyncio.gather(*upload_to_messages)
        return result_photos

    async def _upload_photo(self, upload_url: str, photo_bytes: list, result_photos: list, destination: str = "wall"):
        parts = []
        for ind, photo in enumerate(photo_bytes):
            parts.append(
                reqsnaked.Part(
                    f"file{ind}", photo,
                    mime="multipart/form-data",
                    filename="a.png"
                )
            )

        request = reqsnaked.Request(
            "POST", url=upload_url, multipart=reqsnaked.Multipart(*parts)
        )
        response = await self.requests_session.send(request)
        response = await self.parse_json_body(response)
        if destination == "wall":
            uploaded_photos = await self.method(
                "photos.save_wall_photo", **response.unpack()
            )
        else:
            uploaded_photos = await self.method(
                "photos.save_messages_photo", **response.unpack()
            )
        result_photos.extend(
            Photo(uploaded_photo)
            for uploaded_photo in uploaded_photos
        )

    async def upload_photos_to_wall(
        self, *photos: PhotoEntityTyping, group_id: int = 0
    ) -> typing.List[Photo]:
        """
        Загружает фотографию на стену

        Arguments:
            photos: Фотографии в виде ссылки/пути до файла/сырых байтов/
                IO-хранилища/Path-like объекта
            group_id: ID группы, куда загружаются фотографии. Если
                не передавать, то фотографии загрузятся в скрытый альбом. Рекомендуется
                исключительно для тестирования, т.к. такой альбом имеет лимиты
        Returns:
            Список врапперов загруженных фотографий, который можно напрямую
            передать в поле `attachment` при отправке сообщения
        """
        photo_bytes_coroutines = [
            self._fetch_photo_entity(photo) for photo in photos
        ]
        photo_bytes = await asyncio.gather(*photo_bytes_coroutines)
        uploading_info = await self.method(
            "photos.get_wall_upload_server", group_id=group_id
        )
        result_photos = []
        upload_to_wall = [
            self._upload_photo(
                upload_url=uploading_info["upload_url"].parse(),
                photo_bytes=chunk,
                result_photos=result_photos
            ) for chunk in divide_chunks(photo_bytes, 5)
        ]
        await asyncio.gather(*upload_to_wall)
        return result_photos

    async def upload_video(
        self,
        content: typing.Union[str, bytes],
        name: typing.Optional[str] = None,
        description: typing.Optional[str] = None,
        is_private: typing.Optional[bool] = True,
        wallpost: typing.Optional[bool] = None,
        link: typing.Optional[str] = None,
        group_id: typing.Optional[int] = None,
        album_id: typing.Optional[int] = None,
        privacy_view: typing.Optional[str] = None,
        privacy_comment: typing.Optional[str] = None,
        no_comments: typing.Optional[bool] = None,
        repeat: typing.Optional[bool] = None,
        compression: typing.Optional[bool] = None,
    ):
        """
        Сохраняет видеозапись.
        Arguments:
            content: Содержимое файла видеозаписи.
            name: Название видеофайла. Максимальное количество символов — 128.
            description: Описание видеофайла. Максимальное количество символов — 5 000.
            is_private: Информация о том, можно ли будет отправлять загруженное видео личным сообщением.
            wallpost: Информация о том, опубликовать ли после сохранения запись с видео на стене.
            link: URL источника видеозаписи. Используется для встраивания видео с внешних сайтов, например с YouTube.
            group_id: Идентификатор сообщества, в список видео которого будет сохранён видеофайл. По умолчанию видео сохраняется в список видео текущего пользователя.
            album_id: Идентификатор альбома, в который будет загружено видео.
            privacy_view: Настройки приватности просмотра видео. Указывается в специальном формате. Параметр используется для видео, которые пользователь загрузил в свой профиль.
            privacy_comment: Настройки приватности комментирования видео. Указывается в специальном формате. Параметр используется для видео, которые пользователь загрузил в свой профиль.
            no_comments: Информация о том, нужно ли отключить возможность комментирования видео из сообществ.
            repeat: Информация о том, нужно ли зациклить воспроизведения видео.
            compression: Информация о том, нужно ли сжимать видеозапись.
        Returns:
            None
        """
        data_storage = reqsnaked.Multipart(
            reqsnaked.Part(
                "file", content,
                mime="video/mp4",
                filename="file.mp4"
            )
        )

        uploading_info = await self.method("video.save", is_private=is_private)

        request = reqsnaked.Request(
            "POST", url=uploading_info["upload_url"].parse(), multipart=data_storage
        )
        response = await self.requests_session.send(request)
        response = await self.parse_json_body(response)
        fields = {
            "attachment_type": "video",
            "owner_id": response["owner_id"].parse(),
            "id": response["video_id"].parse(),
            "access_key": response["video_hash"].parse()
        }
        return Video(fields)

    async def upload_doc_to_message(
        self,
        content: typing.Union[str, bytes],
        filename: str,
        *,
        tags: typing.Optional[str] = None,
        return_tags: typing.Optional[bool] = None,
        type: typing.Literal["doc", "audio_message", "graffiti"] = "doc",
        peer_id: int = 0,
    ) -> Document:
        """
        Загружает документ для отправки в сообщение

        Arguments:
            content: Содержимое документа. Документ может быть
                как текстовым, так и содержать сырые байты
            filename: Имя файла
            tags: Теги для файла, используемые при поиске
            return_tags: Возвращать переданные теги при запросе
            type: Тип документа: файл/голосовое сообщение/граффити
            peer_id: ID диалога или беседы, куда загружается документ

        Returns:
            Враппер загруженного документа. Этот объект можно напрямую
            передать в поле `attachment` при отправке сообщения
        """
        if "." not in filename:
            filename = f"{filename}.txt"
        data_storage = reqsnaked.Multipart(
            reqsnaked.Part(
                "file", content,
                mime="multipart/form-data",
                filename=filename
            )
        )

        uploading_info = await self.method(
            "docs.get_messages_upload_server",
            peer_id=peer_id,
            type=type
        )
        request = reqsnaked.Request(
            "POST", url=uploading_info["upload_url"].parse(), multipart=data_storage
        )
        response = await self.requests_session.send(request)
        response = await self.parse_json_body(response)
        document = await self.method(
            "docs.save",
            **response.unpack(),
            title=filename,
            tags=tags,
            return_tags=return_tags,
        )
        return Document(document[type].parse())

    async def upload_video_message(
        self,
        content: typing.Union[str, bytes],
        shape_id: typing.Literal[1, 2, 3, 4, 5] = 1
    ) -> VideoMessage:
        data_storage = reqsnaked.Multipart(
            reqsnaked.Part(
                name="file", value=content,
                mime="video/mp4",
                filename="file.mp4"
            )
        )
        uploading_info = await self.method(
            "video.getVideoMessageUploadInfo",
            shape_id=shape_id
        )
        request = reqsnaked.Request(
            "POST", url=uploading_info["upload_url"].parse(), multipart=data_storage
        )
        response = await self.requests_session.send(request)
        response = await self.parse_json_body(response)
        fields = {
            "attachment_type": "video_message",
            "owner_id": response["owner_id"].parse(),
            "id": response["video_id"].parse(),
            "access_key": response["video_hash"].parse()
        }
        return VideoMessage(fields)

    @property
    def token(self):
        return self._token


def divide_chunks(l: list, size: int):
    # looping till length l
    for i in range(0, len(l), size):
        yield l[i:i + size]


def _convert_param_value(value, /):
    """
    Конвертирует параметр API запроса в соответствии
    с особенностями API и дополнительными удобствами

    Arguments:
        value: Текущее значение параметра

    Returns:
        Новое значение параметра

    """
    # Для всех перечислений функция вызывается рекурсивно.
    # Массивы в запросе распознаются вк только если записать их как строку,
    # перечисляя значения через запятую
    if isinstance(value, (list, set, tuple)):
        updated_sequence = map(_convert_param_value, value)
        return ",".join(updated_sequence)

    # Все словари, как списки, нужно сдампить в JSON
    elif isinstance(value, dict):
        return json_parser_policy.dumps(value)

    # Особенности `reqsnaked`
    elif isinstance(value, bool):
        return int(value)

    # Если класс определяет протокол сериализации под параметр API,
    # используется соответствующий метод
    elif isinstance(value, APISerializableMixin):
        new_value = value.represent_as_api_param()
        return _convert_param_value(new_value)

    else:
        return str(value)


def _convert_params_for_api(params: dict, /):
    """
    Конвертирует словарь из параметров для метода API,
    учитывая определенные особенности

    Arguments:
        params: Параметры, передаваемые для вызова метода API

    Returns:
        Новые параметры, которые можно передать
        в запрос и получить ожидаемый результат

    """
    updated_params = {
        key: _convert_param_value(value)
        for key, value in params.items()
        if value is not None
    }
    return updated_params


def _upper_zero_group(match: typing.Match, /) -> str:
    """
    Поднимает все символы в верхний
    регистр у captured-группы `let`. Используется
    для конвертации snake_case в camelCase.

    Arguments:
      match: Регекс-группа, полученная в результате `re.sub`

    Returns:
        Ту же букву из группы, но в верхнем регистре

    """
    return match.group("let").upper()


def _convert_method_name(name: str, /) -> str:
    """
    Конвертирует snake_case в camelCase.

    Arguments:
      name: Имя метода, который необходимо перевести в camelCase

    Returns:
        Новое имя метода в camelCase

    """
    return re.sub(r"_(?P<let>[a-z])", _upper_zero_group, name)


class CallMethod:

    pattern = "API.{name}({{{params}}})"
    param_pattern = "{key!r}: {value!r}"

    def __init__(self, name: str, **params):
        self.name = name
        self.params = params

    def to_execute(self) -> str:
        params_string = ", ".join(
            self.param_pattern.format(
                key=key, value=_convert_param_value(value)
            )
            for key, value in self.params.items()
        )
        return self.pattern.format(name=self.name, params=params_string)
