python data/corpus_loader.py

기본값은 --table all이라 accidents, laws, chemicals, designs 전부 빌드합니다.

특정 테이블만 하려면:
python data/corpus_loader.py --table chemicals
python data/corpus_loader.py --table laws
python data/corpus_loader.py --table accidents
python data/corpus_loader.py --table designs

---
먼저 chemicals만 테스트해보는 걸 추천합니다. 물질목록순서.md 파싱이 제대로 되는지, chemical_name이 잘 들어가는지 확인한 뒤 전체 빌드하면 시간 낭비가 없습니다.

실행 후 check_db.py로 결과 확인:
python data/check_db.py