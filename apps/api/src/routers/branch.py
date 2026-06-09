"""
Branch Story Router
분기형 스토리 그래프(노드/선택지) 관리
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.dependencies import get_user_key
from src.core.exceptions import NotFoundError, ValidationError
from src.models.db import Book, BranchStoryEdge, BranchStoryNode

router = APIRouter()


class BranchOptionInput(BaseModel):
    option_text: str = Field(min_length=1, max_length=120)
    to_node_key: str = Field(min_length=1, max_length=80)


class BranchNodeInput(BaseModel):
    node_key: str = Field(min_length=1, max_length=80)
    page_number: int = Field(ge=1, le=200)
    text: str = Field(min_length=1, max_length=4000)
    image_url: Optional[str] = Field(default=None, max_length=500)
    options: list[BranchOptionInput] = Field(default_factory=list, max_length=8)


class BranchInitializeRequest(BaseModel):
    nodes: list[BranchNodeInput] = Field(min_length=1, max_length=200)
    overwrite: bool = False


class BranchChoiceRequest(BaseModel):
    current_node_key: str = Field(min_length=1, max_length=80)
    option_text: Optional[str] = Field(default=None, min_length=1, max_length=120)
    to_node_key: Optional[str] = Field(default=None, min_length=1, max_length=80)


async def _ensure_owned_book(*, db: AsyncSession, user_key: str, book_id: str) -> Book:
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise NotFoundError("책", book_id)
    if book.user_key != user_key:
        raise ValidationError("본인의 책만 접근할 수 있습니다.")
    return book


@router.post("/books/{book_id}/initialize")
async def initialize_branch_story(
    book_id: str,
    request: BranchInitializeRequest,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    """
    책의 분기 그래프를 초기화(업서트)한다.

    - overwrite=false: 기존 그래프가 있으면 에러
    - overwrite=true: 기존 노드/엣지를 모두 지우고 재생성
    """
    await _ensure_owned_book(db=db, user_key=user_key, book_id=book_id)

    node_keys = [node.node_key.strip() for node in request.nodes]
    if any(not key for key in node_keys):
        raise ValidationError("node_key는 공백일 수 없습니다.")
    if len(set(node_keys)) != len(node_keys):
        raise ValidationError("중복된 node_key가 있습니다.")

    available_keys = set(node_keys)
    for node in request.nodes:
        seen_option_texts: set[str] = set()
        for option in node.options:
            normalized_option = option.option_text.strip()
            normalized_to_node = option.to_node_key.strip()

            if not normalized_option:
                raise ValidationError("option_text는 공백일 수 없습니다.")
            if not normalized_to_node:
                raise ValidationError("to_node_key는 공백일 수 없습니다.")
            if normalized_option in seen_option_texts:
                raise ValidationError(
                    "하나의 노드에 동일한 선택지 문구를 중복으로 등록할 수 없습니다.",
                    details={
                        "from_node_key": node.node_key.strip(),
                        "option_text": normalized_option,
                    },
                )
            seen_option_texts.add(normalized_option)

            if normalized_to_node not in available_keys:
                raise ValidationError(
                    "존재하지 않는 to_node_key가 있습니다.",
                    details={
                        "from_node_key": node.node_key.strip(),
                        "to_node_key": normalized_to_node,
                    },
                )

    existing_result = await db.execute(
        select(BranchStoryNode).where(BranchStoryNode.book_id == book_id)
    )
    existing_nodes = existing_result.scalars().all()
    if existing_nodes and not request.overwrite:
        raise ValidationError(
            "이미 분기 그래프가 존재합니다. overwrite=true로 재시도하세요."
        )

    if request.overwrite:
        await db.execute(delete(BranchStoryEdge).where(BranchStoryEdge.book_id == book_id))
        await db.execute(delete(BranchStoryNode).where(BranchStoryNode.book_id == book_id))

    edge_count = 0
    for node in request.nodes:
        normalized_node_key = node.node_key.strip()
        db.add(
            BranchStoryNode(
                book_id=book_id,
                node_key=normalized_node_key,
                page_number=node.page_number,
                text=node.text.strip(),
                image_url=node.image_url,
            )
        )
        for option in node.options:
            edge_count += 1
            db.add(
                BranchStoryEdge(
                    book_id=book_id,
                    from_node_key=normalized_node_key,
                    to_node_key=option.to_node_key.strip(),
                    option_text=option.option_text.strip(),
                )
            )

    await db.commit()

    return {
        "status": "success",
        "book_id": book_id,
        "node_count": len(request.nodes),
        "edge_count": edge_count,
        "overwritten": request.overwrite,
    }


@router.get("/books/{book_id}/graph")
async def get_branch_story_graph(
    book_id: str,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    await _ensure_owned_book(db=db, user_key=user_key, book_id=book_id)

    nodes_result = await db.execute(
        select(BranchStoryNode)
        .where(BranchStoryNode.book_id == book_id)
        .order_by(BranchStoryNode.page_number.asc(), BranchStoryNode.node_key.asc())
    )
    edges_result = await db.execute(
        select(BranchStoryEdge)
        .where(BranchStoryEdge.book_id == book_id)
        .order_by(BranchStoryEdge.id.asc())
    )
    nodes = nodes_result.scalars().all()
    edges = edges_result.scalars().all()

    return {
        "book_id": book_id,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": [
            {
                "node_key": node.node_key,
                "page_number": node.page_number,
                "text": node.text,
                "image_url": node.image_url,
            }
            for node in nodes
        ],
        "edges": [
            {
                "from_node_key": edge.from_node_key,
                "to_node_key": edge.to_node_key,
                "option_text": edge.option_text,
            }
            for edge in edges
        ],
    }


@router.post("/books/{book_id}/choose")
async def choose_branch_option(
    book_id: str,
    request: BranchChoiceRequest,
    db: AsyncSession = Depends(get_db),
    user_key: str = Depends(get_user_key),
):
    await _ensure_owned_book(db=db, user_key=user_key, book_id=book_id)

    current_node_key = request.current_node_key.strip()
    raw_option_text = request.option_text
    raw_to_node_key = request.to_node_key
    option_text = raw_option_text.strip() if raw_option_text is not None else None
    to_node_key = raw_to_node_key.strip() if raw_to_node_key is not None else None

    if not current_node_key:
        raise ValidationError("current_node_key는 공백일 수 없습니다.")
    if raw_option_text is not None and not option_text:
        raise ValidationError("option_text는 공백일 수 없습니다.")
    if raw_to_node_key is not None and not to_node_key:
        raise ValidationError("to_node_key는 공백일 수 없습니다.")

    if option_text is None and to_node_key is None:
        raise ValidationError("option_text 또는 to_node_key 중 하나는 필요합니다.")

    current_node_result = await db.execute(
        select(BranchStoryNode).where(
            BranchStoryNode.book_id == book_id,
            BranchStoryNode.node_key == current_node_key,
        )
    )
    current_node = current_node_result.scalar_one_or_none()
    if not current_node:
        raise NotFoundError("분기 노드", current_node_key)

    edges_result = await db.execute(
        select(BranchStoryEdge).where(
            BranchStoryEdge.book_id == book_id,
            BranchStoryEdge.from_node_key == current_node_key,
        )
    )
    available_edges = edges_result.scalars().all()

    if not available_edges:
        return {
            "status": "end",
            "current_node": {
                "node_key": current_node.node_key,
                "text": current_node.text,
                "page_number": current_node.page_number,
            },
            "selected_option": None,
            "next_node": None,
            "is_ending": True,
            "next_options": [],
        }

    chosen = None
    if to_node_key:
        chosen = next(
            (edge for edge in available_edges if edge.to_node_key == to_node_key),
            None,
        )
    if chosen is None and option_text:
        chosen = next(
            (
                edge
                for edge in available_edges
                if edge.option_text.strip() == option_text
            ),
            None,
        )

    if chosen is None:
        raise ValidationError(
            "선택지를 찾을 수 없습니다.",
            details={
                "current_node_key": current_node_key,
                "available_options": [edge.option_text for edge in available_edges],
            },
        )

    next_node_result = await db.execute(
        select(BranchStoryNode).where(
            BranchStoryNode.book_id == book_id,
            BranchStoryNode.node_key == chosen.to_node_key,
        )
    )
    next_node = next_node_result.scalar_one_or_none()
    if not next_node:
        raise ValidationError(
            "다음 노드를 찾을 수 없습니다.",
            details={"to_node_key": chosen.to_node_key},
        )

    next_edges_result = await db.execute(
        select(BranchStoryEdge).where(
            BranchStoryEdge.book_id == book_id,
            BranchStoryEdge.from_node_key == next_node.node_key,
        )
    )
    next_edges = next_edges_result.scalars().all()

    return {
        "status": "ok",
        "current_node": {
            "node_key": current_node.node_key,
            "text": current_node.text,
            "page_number": current_node.page_number,
        },
        "selected_option": chosen.option_text,
        "next_node": {
            "node_key": next_node.node_key,
            "text": next_node.text,
            "page_number": next_node.page_number,
            "image_url": next_node.image_url,
        },
        "is_ending": len(next_edges) == 0,
        "next_options": [
            {
                "option_text": edge.option_text,
                "to_node_key": edge.to_node_key,
            }
            for edge in next_edges
        ],
    }
