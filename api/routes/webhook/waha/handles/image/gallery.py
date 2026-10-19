from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from database.operations.content import MediaRepository
from database.operations.manager import EmbeddingRepository, ModelRepository
from external import embeddings


GALLERY_EMBEDDING_DIMENSION = 2560

def _fit_gallery_embedding(embedding: list[float]) -> list[float]:
    if len(embedding) == GALLERY_EMBEDDING_DIMENSION:
        return embedding
    if len(embedding) > GALLERY_EMBEDDING_DIMENSION:
        return embedding[:GALLERY_EMBEDDING_DIMENSION]
    return embedding + [0.0] * (GALLERY_EMBEDDING_DIMENSION - len(embedding))


async def _get_gallery_query_embedding(query: str, db: AsyncSession) -> list[float]:
    embedding_repo = EmbeddingRepository(db)
    cached_embedding = await embedding_repo.find_by_term(query)
    if cached_embedding:
        return list(cached_embedding.embedding)

    model_repo = ModelRepository(db)
    embedding_model = await model_repo.get_default_embedding_model()
    embedding_json = await embeddings(query, embedding_model.openrouter_id)
    query_embedding = _fit_gallery_embedding(embedding_json["data"][0]["embedding"])

    await embedding_repo.insert_term(query, query_embedding)
    return query_embedding


async def list_images(
        db: AsyncSession, user_id: Optional[int],
        group_id: Optional[int], total: bool = False
) -> str:
    media_repo = MediaRepository(db)

    if user_id:
        medias = await media_repo.find_by_user(user_id)
        context = "suas imagens"
    else:
        medias = await media_repo.find_by_group(group_id, total=total)
        context = "imagens do grupo"

    if not medias:
        return f"*Nenhuma imagem encontrada*\n\nNao ha {context} registradas no ultimo dia."

    images_by_date = {}
    for media in medias:
        date_key = media["inserted_at"].strftime("%d/%m/%Y")
        if date_key not in images_by_date:
            images_by_date[date_key] = []
        images_by_date[date_key].append(media)

    message_parts = [
        "*SUAS IMAGENS RECENTES*" if user_id else "*IMAGENS DO GRUPO*",
        "--------------------------",
        "",
    ]

    total_size = 0

    for date, images in sorted(images_by_date.items(), reverse=True):
        message_parts.append(f"*{date}*")
        message_parts.append("")

        for idx, media in enumerate(images, 1):
            size_mb = media["size"]
            if size_mb < 1:
                size_str = f"{size_mb * 1024:.1f}KB"
            else:
                size_str = f"{size_mb:.1f}MB"

            total_size += size_mb

            time_str = media["inserted_at"].strftime("%H:%M")

            name = media["name"]
            if len(name) > 40:
                name = name[:37] + "..."

            user_info = ""
            if not user_id and "user_name" in media:
                user_info = f" - por {media['user_name']}"

            message_parts.append(
                f"{idx}. *{name}*\n"
                f"   {time_str} - {size_str} - `{media['ext_id']}`{user_info}"
            )

        message_parts.append("")

    message_parts.extend([
        "--------------------------",
        "",
        "*ESTATISTICAS*",
        f"- Total de imagens: *{len(medias)}*",
        f"- Espaco utilizado: *{total_size:.2f}MB*",
        "",
        "--------------------------",
        "",
        "*COMO BUSCAR UMA IMAGEM*",
        "Use o comando de busca semantica:",
        "- `!gallery gato fofo do giovanni`",
        "- `!gallery paisagem montanha com mauricio`",
        "",
        "_Mostrando imagens das ultimas 24h_",
    ])

    return "\n".join(message_parts)


async def search_images(
        query: str,
        user_id: Optional[int],
        group_id: Optional[int],
        db: AsyncSession
) -> str:
    query_embedding = await _get_gallery_query_embedding(query, db)
    media_repo = MediaRepository(db)

    if user_id:
        results = await media_repo.semantic_search_by_user(
            user_id=user_id,
            query_embedding=query_embedding,
            limit=10,
            min_similarity=0.3,
        )
    else:
        results = await media_repo.semantic_search_by_group(
            group_id=group_id,
            query_embedding=query_embedding,
            limit=10,
            min_similarity=0.3,
        )

    if not results:
        return f"*Nenhuma imagem encontrada*\n\nNao encontrei imagens relacionadas a: _{query}_"

    message_parts = [
        f"*RESULTADOS PARA: {query}*",
        "--------------------------",
        "",
    ]

    for idx, media in enumerate(results, 1):
        similarity = media["similarity"] * 100
        time_str = media["inserted_at"].strftime("%d/%m %H:%M")

        message_parts.append(
            f"{idx}. *{media['name']}*\n"
            f"   Match: {similarity:.1f}%\n"
            f"   {time_str} - {media['user_name']}"
        )

    message_parts.extend([
        "",
        "--------------------------",
        f"_Encontrei {len(results)} imagens relevantes_",
        "_Match por descricao da imagem_",
    ])

    return "\n".join(message_parts)
