# MIT License
#
# Copyright (c) 2026 Shreyansh Srivastava
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

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
