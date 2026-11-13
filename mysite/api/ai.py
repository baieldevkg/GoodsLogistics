import asyncio
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from langchain_core.exceptions import OutputParserException
from mysite.chain.seacrh import search_chain
from mysite.database.schema import ChatInputSchema, ChatOutSchema, ChatItemSchema
from mysite.database.models import Product
from mysite.database.db import SessionLocal


async def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


ai_router = APIRouter(prefix='/ai', tags=['AI Assistant'])


@ai_router.post('/chat', response_model=ChatOutSchema)
async def chat(data: ChatInputSchema, db: Session = Depends(get_db)):
    question = data.question.strip()

    if not question:
        raise HTTPException(status_code=422, detail='Маалымат туура эмес формата берилип жатат')

    try:
        params = await asyncio.wait_for(
            search_chain.ainvoke({"text": question}), timeout=120
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=500, detail='Модел тапшырманы аткарганы жетишкен жок')
    except OutputParserException:
        raise HTTPException(status_code=500, detail='Моделдин жообу схемага туура келбейт')

    print('PARAMS:', params)

    q = f' {question.lower()} '
    if ' до ' in q and ' от ' not in q:
        if params.get('min_price') is not None and params.get('max_price') is None:
            params['max_price'] = params['min_price']
            params['min_price'] = None

    if not params.get('allowed'):
        return ChatOutSchema(answer='Подходящие товары не найдены.', items=[])

    query = db.query(Product)

    if params.get('store_id') is not None:
        query = query.filter(Product.store_id == params['store_id'])
    if params.get('min_price') is not None:
        query = query.filter(Product.price >= params['min_price'])
    if params.get('max_price') is not None:
        query = query.filter(Product.price <= params['max_price'])
    if params.get('is_original') is not None:
        query = query.filter(Product.is_original == params['is_original'])

    if params.get('sort') == 'asc':
        query = query.order_by(Product.price.asc())
    elif params.get('sort') == 'desc':
        query = query.order_by(Product.price.desc())

    products = query.all()

    name = (params.get('product_name') or '').strip().lower()
    if name:
        stems = [w[:5] for w in name.split() if len(w) > 2]
        products = [
            p for p in products
            if any(
                s in p.product_name.lower() or s in (p.description or '').lower()
                for s in stems
            )
        ]

    if not products:
        return ChatOutSchema(answer='Подходящие товары не найдены.', items=[])

    answer = 'Найден подходящий товар' if len(products) == 1 else f'Найдено товаров: {len(products)}'

    return ChatOutSchema(
        answer=answer,
        items=[ChatItemSchema.model_validate(p) for p in products]
    )