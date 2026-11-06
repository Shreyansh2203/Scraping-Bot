from __future__ import annotations

from aiogram import Router, types
from aiogram.filters import Command

router = Router()


@router.message(Command("start"))
async def cmd_start(message: types.Message) -> None:
    await message.reply(
        "👋 Send me an Instagram or Twitter/X video URL and I'll download it for you.\n\n"
        "Supported:\n"
        "• instagram.com/reel/...\n"
        "• instagram.com/p/...\n"
        "• x.com/.../status/...\n"
        "• twitter.com/.../status/..."
    )


@router.message(Command("help"))
async def cmd_help(message: types.Message) -> None:
    await message.reply(
        "Just paste a video URL and I'll fetch the best quality version.\n\n"
        "If a download fails, it may be private, suspended, or blocked."
    )
