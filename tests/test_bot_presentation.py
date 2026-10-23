from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import SetMyCommands

from app.bot_profile import ABOUT, AVATAR, DESCRIPTION, NAME, apply_profile
from app.chat_formatting import student_profile
from app.commands import CommandMenu, chat_commands
from registrar.models import Student


def test_profile_copy_fits_telegram_limits_and_avatar_is_a_real_jpeg():
    assert 1 <= len(NAME) <= 64
    assert 1 <= len(ABOUT) <= 120
    assert 1 <= len(DESCRIPTION) <= 512
    assert AVATAR.read_bytes().startswith(b"\xff\xd8\xff")
    assert "/new_event" in DESCRIPTION


def test_profile_entities_keep_special_characters_and_copyable_student_id():
    person = Student(
        "00000001", "😀 <Name> & Student", "student@example.test", account="00000001@example.test"
    )
    text, entities = student_profile(person).render()
    assert "Name: 😀 <Name> & Student" in text
    assert {entity.type for entity in entities} == {"bold", "code"}
    codes = [
        text.encode("utf-16-le")[item.offset * 2 : (item.offset + item.length) * 2].decode(
            "utf-16-le"
        )
        for item in entities
        if item.type == "code"
    ]
    assert codes == ["00000001", "00000001@example.test"]


def test_command_visibility_matches_registration_and_organizer_permissions():
    visitor = [item.command for item in chat_commands()]
    student = [item.command for item in chat_commands(registered=True)]
    organizer = [item.command for item in chat_commands(registered=True, organizer=True)]
    assert "resend" in visitor and "new_event" not in visitor and "panel" not in visitor
    assert "new_event" in student and "resend" not in student and "panel" not in student
    assert "panel" in organizer
    assert "me" not in visitor and "me" in student and "me" in organizer
    assert student[-3:] == organizer[-3:] == ["me", "help", "info"]
    for commands in (visitor, student, organizer):
        assert commands[-2:] == ["help", "info"]
        assert not {"find", "members", "send", "mail", "cancel"} & set(commands)


@pytest.mark.asyncio
async def test_menu_sync_updates_roles_and_expires_without_a_request_per_message():
    now = [0]
    service = CommandMenu(clock=lambda: now[0], max_entries=2)
    bot = AsyncMock()
    await service.sync(bot, 100)
    await service.sync(bot, 100)
    bot.set_my_commands.assert_awaited_once()
    await service.sync(bot, 100, registered=True)
    assert bot.set_my_commands.await_count == 2
    assert "resend" not in [item.command for item in bot.set_my_commands.await_args.args[0]]
    await service.sync(bot, 100, registered=True, organizer=True)
    assert "panel" in [item.command for item in bot.set_my_commands.await_args.args[0]]
    now[0] += 3601
    await service.sync(bot, 100, registered=True, organizer=True)
    assert bot.set_my_commands.await_count == 4
    await service.sync(bot, 200)
    await service.sync(bot, 300)
    await service.sync(bot, 100, registered=True, organizer=True)
    assert bot.set_my_commands.await_count == 7


@pytest.mark.asyncio
async def test_failed_menu_sync_is_nonfatal_private_and_retried(caplog):
    bot = AsyncMock()
    bot.set_my_commands.side_effect = [
        TelegramNetworkError(method=SetMyCommands(commands=[]), message="private-token-url"),
        True,
    ]
    service = CommandMenu()
    await service.sync(bot, 100)
    await service.sync(bot, 100)
    assert bot.set_my_commands.await_count == 2
    assert "private-token-url" not in caplog.text
    assert "TelegramNetworkError" in caplog.text


@pytest.mark.asyncio
async def test_profile_setup_changes_metadata_without_sending_messages_or_reuploading_photo():
    bot = AsyncMock()
    bot.get_my_name.return_value = SimpleNamespace(name="Old name")
    bot.get_my_description.return_value = SimpleNamespace(description="")
    bot.get_my_short_description.return_value = SimpleNamespace(short_description="")
    await apply_profile(bot)
    bot.set_my_name.assert_awaited_once_with(name=NAME)
    bot.set_my_description.assert_awaited_once_with(description=DESCRIPTION)
    bot.set_my_short_description.assert_awaited_once_with(short_description=ABOUT)
    bot.send_message.assert_not_called()
    bot.set_my_profile_photo.assert_not_called()
    bot.get_my_name.return_value = SimpleNamespace(name=NAME)
    bot.get_my_description.return_value = SimpleNamespace(description=DESCRIPTION)
    bot.get_my_short_description.return_value = SimpleNamespace(short_description=ABOUT)
    for method in (bot.set_my_name, bot.set_my_description, bot.set_my_short_description):
        method.reset_mock()
    await apply_profile(bot, upload_photo=True)
    bot.set_my_name.assert_not_called()
    bot.set_my_description.assert_not_called()
    bot.set_my_short_description.assert_not_called()
    bot.set_my_profile_photo.assert_awaited_once()
    bot.send_message.assert_not_called()
