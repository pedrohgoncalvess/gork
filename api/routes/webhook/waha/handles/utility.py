import calendar
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from agents.resume.agent import get_resume_conversation
from api.routes.webhook.waha.handles.core import COMMANDS
from database import PgConnection
from database.models.manager.interaction import Interaction
from database.operations.manager import InteractionRepository, ModelRepository
from external.waha import send_message


# ── Token consumption ────────────────────────────────────────────────────────

MAX_USAGE_PERIODS = 60


class UsageParameterError(ValueError):
    pass


def _usage_unit(value: object, default: str = "d") -> str:
    normalized = str(value or default).strip().lower()
    aliases = {
        "d": "d", "day": "d", "days": "d", "daily": "d", "24h": "d",
        "w": "w", "week": "w", "weeks": "w", "weekly": "w",
        "m": "m", "month": "m", "months": "m", "monthly": "m",
    }
    unit = aliases.get(normalized)
    if not unit:
        raise UsageParameterError(
            "Granularidade inválida. Use d/day, w/week ou m/month."
        )
    return unit


def _usage_range(value: object, default_unit: str = "d") -> tuple[int, str]:
    normalized = str(value or f"1{default_unit}").strip().lower()
    match = re.fullmatch(r"(\d+)\s*([a-z]+)?", normalized)
    if not match:
        raise UsageParameterError(
            "Período inválido. Use, por exemplo, 7d, 3w ou 2m."
        )
    amount = int(match.group(1))
    if amount < 1:
        raise UsageParameterError("O período precisa ser maior que zero.")
    return amount, _usage_unit(match.group(2) or default_unit)


def _shift_usage_time(value: datetime, amount: int, unit: str) -> datetime:
    if unit == "d":
        return value - timedelta(days=amount)
    if unit == "w":
        return value - timedelta(weeks=amount)

    month_index = value.year * 12 + value.month - 1 - amount
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _usage_periods(
    end_date: datetime,
    amount: int,
    range_unit: str,
    granularity: str,
) -> list[tuple[datetime, datetime]]:
    start_date = _shift_usage_time(end_date, amount, range_unit)
    periods = []
    cursor = end_date
    while cursor > start_date:
        period_start = max(start_date, _shift_usage_time(cursor, 1, granularity))
        periods.append((period_start, cursor))
        cursor = period_start
        if len(periods) > MAX_USAGE_PERIODS:
            raise UsageParameterError(
                f"Esse período gera mais de {MAX_USAGE_PERIODS} intervalos. "
                "Aumente a granularidade."
            )
    periods.reverse()
    return periods


def _usage_totals(consumption_data: list[dict]) -> dict:
    return {
        "interactions": sum(user["total_interactions"] for user in consumption_data),
        "input_tokens": sum(user["total_input_tokens"] for user in consumption_data),
        "output_tokens": sum(user["total_output_tokens"] for user in consumption_data),
        "tokens": sum(user["total_tokens"] for user in consumption_data),
        "cost": sum(user["estimated_cost"] for user in consumption_data),
    }


def _usage_period_label(start_date: datetime, end_date: datetime, unit: str) -> str:
    if unit == "d":
        return f"{start_date:%d/%m %H:%M}–{end_date:%d/%m %H:%M}"
    return f"{start_date:%d/%m/%Y}–{end_date:%d/%m/%Y}"


def _format_usage_user(index: int, user: dict) -> list[str]:
    phone_number = user.get("user_phone_number") or "número não informado"
    user_name = user.get("user_name") or "Usuário sem nome"
    return [
        f"{index}. *{user_name}*",
        f"   📞 {phone_number}",
        f"   💬 {user['total_interactions']:,} interações | "
        f"🔢 {user['total_tokens']:,} tokens | "
        f"💰 ${user['estimated_cost']:.6f}",
    ]


async def token_consumption(
    user_id: Optional[int] = None,
    group_id: Optional[int] = None,
    user_name: Optional[str] = None,
    when: object = None,
    granularity: object = None,
) -> str:
    normalized_user_name = (
        str(user_name).strip()
        if user_name is not None and str(user_name).strip()
        else None
    )
    try:
        granularity_unit = _usage_unit(granularity, default="d")
        amount, range_unit = _usage_range(when, default_unit=granularity_unit)
        end_date = datetime.now().astimezone()
        periods = _usage_periods(
            end_date,
            amount,
            range_unit,
            granularity_unit,
        )
    except UsageParameterError as error:
        return f"📊 *Relatório de Uso*\n\n❌ {error}"

    start_date = periods[0][0]
    async with PgConnection() as db:
        interaction_repo = InteractionRepository(Interaction, db)

        consumption_data = await interaction_repo.get_consumption_by_user(
            group_id=group_id,
            user_id=user_id,
            user_name=normalized_user_name if user_id is None else None,
            start_date=start_date,
            end_date=end_date,
        )

        if not consumption_data:
            target = f' para "{normalized_user_name}"' if normalized_user_name else ""
            return (
                "📊 *Relatório de Uso*\n\n"
                f"❌ Nenhum dado encontrado{target} entre "
                f"{start_date:%d/%m/%Y %H:%M} e agora."
            )

        if normalized_user_name:
            message_parts = [
                "📊 *RELATÓRIO DE USO*",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━",
                f"📅 Período: {start_date:%d/%m/%Y %H:%M} até agora",
                "👥 *USUÁRIOS ENCONTRADOS*",
            ]
            for index, user in enumerate(consumption_data, 1):
                message_parts.extend(_format_usage_user(index, user))
                message_parts.extend([
                    "",
                    f"   💬 Interações: {user['total_interactions']:,}",
                    f"   🔢 Tokens: {user['total_tokens']:,}",
                    f"     ├─ 📥 Input: {user['total_input_tokens']:,}",
                    f"     └─ 📤 Output: {user['total_output_tokens']:,}",
                    f"   💰 Custo: ${user['estimated_cost']:.6f} USD",
                    "",
                    "   📆 *CONSUMO POR PERÍODO*",
                ])
                for period_start, period_end in periods:
                    period_data = await interaction_repo.get_consumption_by_user(
                        group_id=group_id,
                        user_id=user["user_id"],
                        start_date=period_start,
                        end_date=period_end,
                    )
                    period_totals = _usage_totals(period_data)
                    label = _usage_period_label(period_start, period_end, granularity_unit)
                    message_parts.append(
                        f"   • {label}: {period_totals['interactions']:,} interações | "
                        f"{period_totals['tokens']:,} tokens | ${period_totals['cost']:.6f}"
                    )
                message_parts.append("")

            message_parts.extend([
                "━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "*💡 Relatório gerado automaticamente*",
            ])
            return "\n".join(message_parts)

        totals = _usage_totals(consumption_data)
        granularity_labels = {"d": "24 horas", "w": "semana", "m": "mês"}
        message_parts = [
            "📊 *SEU RELATÓRIO DE USO*" if user_id is not None else "📊 *RELATÓRIO DE USO*",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"📅 Período: {start_date:%d/%m/%Y %H:%M} até agora",
            f"⏱ Agrupamento: {granularity_labels[granularity_unit]}",
        ]
        if normalized_user_name:
            message_parts.append(f"👤 Usuário contém: {normalized_user_name}")

        message_parts.extend([
            "",
            "📈 *RESUMO*",
            f"💬 Interações: {totals['interactions']:,}",
            f"🔢 Tokens: {totals['tokens']:,}",
            f"  ├─ 📥 Input: {totals['input_tokens']:,}",
            f"  └─ 📤 Output: {totals['output_tokens']:,}",
            f"💰 Custo: ${totals['cost']:.6f} USD",
            "",
            "📆 *CONSUMO POR PERÍODO*",
        ])

        for period_start, period_end in periods:
            period_data = await interaction_repo.get_consumption_by_user(
                group_id=group_id,
                user_id=user_id,
                user_name=normalized_user_name if user_id is None else None,
                start_date=period_start,
                end_date=period_end,
            )
            period_totals = _usage_totals(period_data)
            label = _usage_period_label(period_start, period_end, granularity_unit)
            message_parts.append(
                f"• {label}: {period_totals['interactions']:,} interações | "
                f"{period_totals['tokens']:,} tokens | ${period_totals['cost']:.6f}"
            )

        if user_id is None:
            users_to_show = consumption_data if normalized_user_name else consumption_data[:10]
            section_title = (
                "👥 *USUÁRIOS ENCONTRADOS*"
                if normalized_user_name
                else "👥 *USUÁRIOS POR CUSTO*"
            )
            message_parts.extend(["", section_title])
            for index, user in enumerate(users_to_show, 1):
                message_parts.extend(_format_usage_user(index, user))

        message_parts.extend([
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "_💡 Relatório gerado automaticamente_",
        ])
        return "\n".join(message_parts)


# ── Handles ──────────────────────────────────────────────────────────────────

async def handle_help_command(remote_id: str, message_id: str):
    category_info = {
        "interaction": ("💬 *INTERAÇÃO*", []),
        "search": ("🔍 *BUSCA & INFORMAÇÃO*", []),
        "audio": ("🎙️ *ÁUDIO & TRANSCRIÇÃO*", []),
        "image": ("🖼️ *IMAGENS & STICKERS*", []),
        "video": ("🎬 *VÍDEOS*", []),
        "reminder": ("⏰ *LEMBRETES*", []),
        "utility": ("📝 *UTILIDADES*", []),
        "media": ("📹 *MÍDIA*", []),
    }

    for cmd, desc, category, params in COMMANDS:
        if category != "hidden" and desc:
            category_info[category][1].append((cmd, desc, params))

    help_parts = [
        "🤖 *COMANDOS DO GORK*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ""
    ]

    for category, (title, commands) in category_info.items():
        if commands:
            help_parts.append(title)
            for cmd, desc, params in commands:
                help_parts.append(f"*{cmd}* - {desc}")

                if params:
                    help_parts.append("  _Parâmetros:_")
                    for param_name, param_desc, param_options in params:
                        help_parts.append(f"  • *{param_name}* - {param_desc}")
                        if param_options:
                            options_str = "\n".join([f"        - _{opt}_ ({desc})" for opt, desc in param_options])
                            help_parts.append(f"    Opções:\n {options_str}")

            help_parts.append("")

    help_parts.extend([
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "💡 *DICA: FALE NATURALMENTE!*",
        "",
        "Você não precisa usar comandos. Apenas converse normalmente:",
        "",
        "• \"me avisa amanhã às 10h\"",
        "  → _cria lembrete automaticamente_",
        "",
        "• \"pesquisa sobre Python\"",
        "  → _busca na internet_",
        "",
        "• \"cria uma imagem de gato espacial\"",
        "  → _gera a imagem_",
        "",
        "• \"resume a conversa\"",
        "  → _faz resumo do histórico_",
        "",
        "Os comandos (!) são *opcionais*, mas mais rápidos, precisos e econômicos.",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🔗 Contribute: github.com/pedrohgoncalvess/gork"
    ])

    help_message = "\n".join(help_parts)
    await send_message(remote_id, help_message, message_id)


async def handle_model_command(remote_id: str, message_id: str, db: AsyncSession):
    model_repo = ModelRepository(db)
    model = await model_repo.get_default_model()
    audio_model = await model_repo.get_default_audio_model()
    image_model = await model_repo.get_default_image_model()

    formatted_text = (
        "🤖 *MODELOS EM USO*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💬 *Texto*\n"
        f"└─ _{model.name if model else 'Não configurado'}_\n\n"
        f"🎙️ *Áudio*\n"
        f"└─ _{audio_model.name if audio_model else 'Não configurado'}_\n\n"
        f"🖼️ *Imagem*\n"
        f"└─ _{image_model.name if image_model else 'Não configurado'}_\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "_💡 Modelos padrão do sistema_"
    )
    await send_message(remote_id, formatted_text, message_id)


async def handle_resume_command(
        remote_id: str,
        message_id: str,
        user_id: int,
        group_id: Optional[int] = None
):
    resume = await get_resume_conversation(user_id, group_id=group_id)
    await send_message(remote_id, resume, message_id)


async def handle_consumption_command(
        remote_id: str,
        user_id: Optional[int] = None,
        group_id: Optional[int] = None,
        user_name: Optional[str] = None,
        when: object = None,
        granularity: object = None,
):
    analytics = await token_consumption(
        user_id=user_id,
        group_id=group_id,
        user_name=user_name if user_id is None else None,
        when=when,
        granularity=granularity,
    )

    await send_message(remote_id, analytics)
    return
