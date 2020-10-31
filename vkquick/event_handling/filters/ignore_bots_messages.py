import typing as ty

import vkquick.event_handling.filters.base
import vkquick.events_generators.event


class IgnoreBotsMessages(vkquick.event_handling.filters.base.Filter):

    passed_decision = "Сообщение отправлено не от бота"
    not_passed_decision = "Сообщение отправлено от бота"

    def make_decision(
            self, event: vkquick.events_generators.event.Event
    ) -> ty.Tuple[bool, str]:
        """
        Проверяет от кого пришло сообщение
        """
        if event.get_message_object().from_id > 0:
            return True, self.passed_decision
        return False, self.not_passed_decision
