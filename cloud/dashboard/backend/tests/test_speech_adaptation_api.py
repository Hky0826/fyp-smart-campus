import sys
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.models import Base, SpeechLanguage, SpeechAdaptationPhrase
from app.db_init import ensure_speech_tables_and_seed


def test_speech_languages_and_phrases_seed_and_operations():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    session = TestingSessionLocal()

    try:
        # 1. Run idempotent seeding
        ensure_speech_tables_and_seed(db=session)

        # 2. Verify seeded languages
        languages = session.query(SpeechLanguage).all()
        assert len(languages) >= 10
        lang_map = {l.language_code: l for l in languages}

        assert "en" in lang_map
        assert lang_map["en"].is_default is True
        assert lang_map["en"].is_active is True

        assert "zh" in lang_map
        assert lang_map["zh"].is_default is True

        assert "yue" in lang_map
        assert lang_map["yue"].is_default is True

        assert "ms" in lang_map
        assert lang_map["ms"].is_default is True

        assert "ja" in lang_map
        assert lang_map["ja"].is_default is False
        assert lang_map["ja"].is_active is True

        assert "ta" in lang_map
        assert lang_map["ta"].is_active is True

        # 3. Verify seeded adaptation phrases
        phrases = session.query(SpeechAdaptationPhrase).all()
        assert len(phrases) >= 30
        phrase_texts = [p.phrase for p in phrases]
        assert "Quest International University" in phrase_texts
        assert "QIU" in phrase_texts
        assert "Faculty of Computing" in phrase_texts
        assert "Perpustakaan" in phrase_texts
        assert "大学" in phrase_texts
        assert "邊度" in phrase_texts

        # 4. Test Toggle Default Language
        lang_ja = lang_map["ja"]
        lang_ja.is_default = not lang_ja.is_default
        session.commit()
        session.refresh(lang_ja)
        assert lang_ja.is_default is True

        # 5. Test Toggle Active Language
        lang_ja.is_active = False
        session.commit()
        session.refresh(lang_ja)
        assert lang_ja.is_active is False

        # 6. Test Add New Adaptation Phrase
        new_phrase = SpeechAdaptationPhrase(
            phrase="Dewan Canselor",
            language_category="CAMPUS",
            description="Main chancellor hall in Malay",
            is_active=True,
        )
        session.add(new_phrase)
        session.commit()
        session.refresh(new_phrase)
        assert new_phrase.phrase_id is not None
        assert new_phrase.phrase == "Dewan Canselor"

        # 7. Test Update Phrase
        new_phrase.description = "Updated hall description"
        session.commit()
        session.refresh(new_phrase)
        assert new_phrase.description == "Updated hall description"

        # 8. Test Toggle Phrase Active
        new_phrase.is_active = False
        session.commit()
        session.refresh(new_phrase)
        assert new_phrase.is_active is False

        # 9. Test Delete Phrase
        session.delete(new_phrase)
        session.commit()
        deleted = session.query(SpeechAdaptationPhrase).filter(SpeechAdaptationPhrase.phrase == "Dewan Canselor").first()
        assert deleted is None

        # 10. Test Distinct Categories
        cats = session.query(SpeechAdaptationPhrase.language_category).distinct().all()
        cat_names = sorted([c[0] for c in cats if c[0]])
        assert "CAMPUS" in cat_names
        assert "ACADEMIC" in cat_names
        assert "MALAY" in cat_names
        assert "CHINESE" in cat_names
        assert "CANTONESE" in cat_names

    finally:
        session.close()
