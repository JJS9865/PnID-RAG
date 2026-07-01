import lancedb

uri = "C:/PnID_RAG/vector_db"

try:
    db = lancedb.connect(uri)
    print("✅ 성공: LanceDB에 정상적으로 연결되었습니다.\n")

    result = db.list_tables()
    tables = result.tables if hasattr(result, "tables") else list(result)
    print(f"📂 존재하는 테이블 목록: {tables}\n")

    if not tables:
        print("⚠️ 경고: DB는 생성되었으나 안에 테이블이 없습니다.")
    else:
        for table_name in tables:
            print("=" * 60)
            print(f"▶ [{table_name}] 테이블 점검 시작")

            tbl = db.open_table(table_name)
            row_count = len(tbl)
            print(f"📊 총 레코드 수: {row_count} 개")

            if row_count == 0:
                print("⚠️ 경고: 테이블은 존재하지만 데이터(레코드)가 0개입니다.\n")
                continue

            print("\n구조(Schema):")
            for field in tbl.schema:
                print(f" - {field.name}: {field.type}")

            print("\n🔍 샘플 데이터 (상위 3개):")
            sample_df = tbl.head(3).to_pandas()
            for col in sample_df.columns:
                dtype = sample_df[col].dtype
                val = sample_df[col].iloc[0]
                # 벡터 컬럼은 앞 5개 값만 표시
                if "vector" in col.lower():
                    preview = list(val[:5]) if hasattr(val, "__len__") else val
                    print(f"  [{col}] ({dtype}): {preview}... (dim={len(val) if hasattr(val, '__len__') else '?'})")
                elif isinstance(val, str) and len(val) > 100:
                    print(f"  [{col}] ({dtype}): {val[:100]}...")
                else:
                    print(f"  [{col}] ({dtype}): {val}")
            print()

except Exception as e:
    print(f"❌ 오류 발생: DB를 읽는 중 문제가 발생했습니다.\n상세 내용: {e}")
