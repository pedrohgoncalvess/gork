from typing import Optional
from datetime import datetime, timedelta

from database import PgConnection
from database.models.manager import Interaction
from database.operations.manager import InteractionRepository


async def token_consumption(user_id: Optional[int] = None, group_id: Optional[int] = None) -> str:
    async with PgConnection() as db:
        interaction_repo = InteractionRepository(Interaction, db)

        consumption_data = await interaction_repo.get_consumption_by_user(
            group_id=group_id
        )

        if user_id is not None:
            consumption_data = [user for user in consumption_data if user['user_id'] == user_id]

        if not consumption_data:
            if user_id is not None:
                return "📊 *Seu Consumo de Tokens*\n\n❌ Você não possui nenhuma interação registrada nas últimas 24 horas."
            elif group_id:
                return "📊 *Relatório de Consumo de Tokens*\n\n❌ Nenhum dado encontrado para este grupo nas últimas 24 horas."
            else:
                return "📊 *Relatório de Consumo de Tokens*\n\n❌ Nenhum dado encontrado nas últimas 24 horas."

        total_interactions = sum(user['total_interactions'] for user in consumption_data)
        total_input_tokens = sum(user['total_input_tokens'] for user in consumption_data)
        total_output_tokens = sum(user['total_output_tokens'] for user in consumption_data)
        total_tokens = sum(user['total_tokens'] for user in consumption_data)
        total_cost = sum(user['estimated_cost'] for user in consumption_data)

        start_date = datetime.now() - timedelta(days=1)
        period_text = f"📅 Período: {start_date.strftime('%d/%m/%Y %H:%M')} até agora"

        if user_id is not None and len(consumption_data) == 1:
            user = consumption_data[0]

            message_parts = [
                "📊 *SEU CONSUMO DE TOKENS*",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━",
                period_text,
                "",
                "📈 *RESUMO*",
                f"💬 Interações: {user['total_interactions']:,}",
                f"🔢 Tokens Totais: {user['total_tokens']:,}",
                f"  ├─ 📥 Input: {user['total_input_tokens']:,}",
                f"  └─ 📤 Output: {user['total_output_tokens']:,}",
                f"💰 Custo Estimado: ${user['estimated_cost']:.6f} USD",
                ""
            ]

            if user['models_used']:
                message_parts.extend([
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━",
                    "🤖 *MODELOS UTILIZADOS:*"
                ])

                for model in user['models_used']:
                    message_parts.extend([
                        "",
                        f"• *{model['model_name']}*",
                        f"  ├─ Interações: {model['interaction_count']:,}",
                        f"  ├─ Tokens: {model['total_tokens']:,}",
                        f"  │   ├─ Input: {model['input_tokens']:,}",
                        f"  │   └─ Output: {model['output_tokens']:,}",
                        f"  └─ Custo: ${model['estimated_cost']:.6f}"
                    ])

            message_parts.extend([
                "",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "_💡 Relatório gerado automaticamente_"
            ])

        else:
            message_parts = [
                "📊 *RELATÓRIO DE CONSUMO DE TOKENS*",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━",
                period_text
            ]

            message_parts.extend([
                "",
                "📈 *RESUMO GERAL*",
                f"💬 Total de Interações: {total_interactions:,}",
                f"🔢 Total de Tokens: {total_tokens:,}",
                f"  ├─ 📥 Input: {total_input_tokens:,}",
                f"  └─ 📤 Output: {total_output_tokens:,}",
                f"💰 Custo Estimado: ${total_cost:.6f} USD",
                "",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "",
                f"👥 *TOP {len(consumption_data)} USUÁRIOS POR CUSTO:*"
            ])

            for idx, user in enumerate(consumption_data[:10], 1):
                percentage = (user['estimated_cost'] / total_cost * 100) if total_cost > 0 else 0

                message_parts.extend([
                    "",
                    f"*{idx}. {user['user_name']}*",
                    f"├─ 💰 ${user['estimated_cost']:.6f} ({percentage:.1f}%)",
                    f"├─ 💬 {user['total_interactions']:,} interações",
                    f"├─ 🔢 {user['total_tokens']:,} tokens",
                    f"└─ 🤖 {len(user['models_used'])} modelo(s)"
                ])

            if len(consumption_data) > 10:
                message_parts.append(f"\n_... e mais {len(consumption_data) - 10} usuário(s)_")

            message_parts.extend([
                "",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "_💡 Relatório gerado automaticamente_"
            ])

        return "\n".join(message_parts)