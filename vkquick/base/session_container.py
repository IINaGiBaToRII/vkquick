from __future__ import annotations

import dataclasses
import typing

import reqsnaked

from vkquick.json_parsers import BaseJSONParser, json_parser_policy


@dataclasses.dataclass
class RawJSON:
    lazy_json: "reqsnaked.LazyJSON"
    base_path: list = dataclasses.field(default_factory=list)

    def contains(self, *items):
        try:
            return self.query(*self.base_path, *items)
        except KeyError:
            return False

    def query(self, *items):
        return self.lazy_json.query(*self.base_path, *items)

    def __getitem__(self, item):
        return self.query(item)


class SessionContainerMixin:
    """
    Этот класс позволяет удобным способ содержать инстанс `aiohttp.ClientSession`.
    Поскольку инициализации сессии может происходить только уже с запущенным циклом
    событий, это может вызывать некоторые проблемы при попытке создать
    сессию внутри `__init__`.

    Кроме хранения сессию, к которой внутри вашего класса можно
    обратится через `requests_session`, этот класс позволяет передавать
    кастомные сессии `aiohttp` и JSON-парсеры. Используйте соответствующие аргументы
    в `__init__` своего класса, чтобы предоставить возможность пользователю передать
    собственные имплементации или сессию со своими настройками.
    """

    def __init__(
        self,
        *,
        requests_session: typing.Optional[reqsnaked.Client] = None,
        json_parser: typing.Optional[BaseJSONParser] = None,
    ) -> None:
        """
        Arguments:
            requests_session: Кастомная `aiohttp`-сессия для HTTP запросов.
            json_parser: Кастомный парсер, имплементирующий методы
                сериализации/десериализации JSON.
        """
        self.requests_session = reqsnaked.Client()
        self.__json_parser = json_parser or json_parser_policy

    async def __aenter__(self) -> SessionContainerMixin:
        """
        Позволяет автоматически закрыть сессию
        запросов по выходу из `async with` блока.
        """
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    async def parse_json_body(
        self,
        response: reqsnaked.Response,
    ) -> RawJSON:
        """
        Используйте в классе вместо прямого использования `.json()`
        для получения JSON из body ответа. Этот метод использует
        переданный JSON парсер в качестве десериализатора.

        Arguments:
            response: Ответ, пришедший от отправки запроса.
        Returns:
            Словарь, полученный при декодировании ответа.
        """
        return RawJSON(await response.json())
