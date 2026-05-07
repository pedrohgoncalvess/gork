from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content import Media
from database.operations.content import MediaRepository
from embeddings import generate_text_embeddings


async def list_images(db: AsyncSession, user_id: Optional[int], group_id: Optional[int],) -> str:
    media_repo = MediaRepository(db)

    if user_id:
        medias = await media_repo.find_by_user(user_id)
        context = "suas imagens"
    else:
        medias = await media_repo.find_by_group(group_id)
        context = "imagens do grupo"

    if not medias:
        return f"📭 *Nenhuma imagem encontrada*\n\nNão há {context} registradas no último dia."

    images_by_date = {}
    for media in medias:
        date_key = media['inserted_at'].strftime('%d/%m/%Y')
        if date_key not in images_by_date:
            images_by_date[date_key] = []
        images_by_date[date_key].append(media)

    message_parts = [
        "🖼️ *SUAS IMAGENS RECENTES*" if user_id else "🖼️ *IMAGENS DO GRUPO*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ""
    ]

    total_size = 0

    for date, images in sorted(images_by_date.items(), reverse=True):
        message_parts.append(f"📅 *{date}*")
        message_parts.append("")

        for idx, media in enumerate(images, 1):
            size_mb = media['size']
            if size_mb < 1:
                size_str = f"{size_mb * 1024:.1f}KB"
            else:
                size_str = f"{size_mb:.1f}MB"

            total_size += size_mb

            time_str = media['inserted_at'].strftime('%H:%M')

            name = media['name']
            if len(name) > 40:
                name = name[:37] + "..."

            user_info = ""
            if not user_id and 'user_name' in media:
                user_info = f" • _por {media['user_name']}_"

            message_parts.append(
                f"{idx}. *{name}*\n"
                f"   ⏰ {time_str} • 📦 {size_str} • 🆔 `{media['ext_id']}`{user_info}"
            )

        message_parts.append("")

    message_parts.extend([
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"📊 *ESTATÍSTICAS*",
        f"• Total de imagens: *{len(medias)}*",
        f"• Espaço utilizado: *{total_size:.2f}MB*",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "💡 *COMO BUSCAR UMA IMAGEM*",
        "Use o comando de busca semântica:",
        "• `!gallery gato fofo`",
        "• `!gallery paisagem montanha`",
        "",
        "_Mostrando imagens das últimas 24h_"
    ])

    return "\n".join(message_parts)


async def search_images(
        query: str,
        user_id: Optional[int],
        group_id: Optional[int],
        db: AsyncSession
) -> str:
    query_embedding = await generate_text_embeddings(query)
    media_repo = MediaRepository(db)

    if user_id:
        results = await media_repo.semantic_search_by_user(
            user_id=user_id,
            query_embedding=query_embedding,
            limit=10,
            min_similarity=0.5
        )
    else:
        results = await media_repo.semantic_search_by_group(
            group_id=group_id,
            query_embedding=query_embedding,
            limit=10,
            min_similarity=0.5
        )

    if not results:
        return f"🔍 *Nenhuma imagem encontrada*\n\nNão encontrei imagens relacionadas a: _{query}_"

    message_parts = [
        f"🔍 *RESULTADOS PARA: {query}*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ""
    ]

    for idx, media in enumerate(results, 1):
        name_sim = media['desc_similarity'] * 100
        image_sim = media['image_similarity'] * 100
        best_sim = media['best_similarity'] * 100
        matched_by = media['matched_by']
        time_str = media['inserted_at'].strftime('%d/%m %H:%M')

        match_emoji = "📝" if matched_by == "name" else "🖼️"

        message_parts.append(
            f"{idx}. *{media['name']}*\n"
            f"   {match_emoji} Match: {best_sim:.1f}% • "
            f"📝 Nome: {name_sim:.0f}% • "
            f"🖼️ Imagem: {image_sim:.0f}%\n"
            f"   ⏰ {time_str} • 👤 {media['user_name']}"
        )

    message_parts.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"_Encontrei {len(results)} imagens relevantes_",
        f"_📝 = Match por nome | 🖼️ = Match por conteúdo da imagem_"
    ])

    return "\n".join(message_parts)
