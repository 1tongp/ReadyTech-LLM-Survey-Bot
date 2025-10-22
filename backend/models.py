from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Float, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from db import Base

class Survey(Base):
    __tablename__ = "surveys"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    questions = relationship("Question", back_populates="survey", cascade="all, delete-orphan")
    links = relationship("SurveyLink", back_populates="survey", cascade="all, delete-orphan")

class Question(Base):
    __tablename__ = "questions"
    id = Column(Integer, primary_key=True, index=True)
    survey_id = Column(Integer, ForeignKey("surveys.id", ondelete="CASCADE"), index=True, nullable=False)
    order_index = Column(Integer, nullable=False, default=0)
    text = Column(Text, nullable=False)
    type = Column(String(50), nullable=False, default="text")
    survey = relationship("Survey", back_populates="questions")
    answers = relationship("Answer", back_populates="question", cascade="all, delete-orphan")
    guideline = relationship("Guideline", uselist=False, back_populates="question", cascade="all, delete-orphan")

class Guideline(Base):
    __tablename__ = "guidelines"
    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(Integer, ForeignKey("questions.id", ondelete="CASCADE"), unique=True, nullable=False)
    content = Column(Text, nullable=False)
    question = relationship("Question", back_populates="guideline")

class SurveyLink(Base):
    __tablename__ = "survey_links"
    id = Column(Integer, primary_key=True, index=True)
    survey_id = Column(Integer, ForeignKey("surveys.id", ondelete="CASCADE"), index=True, nullable=False)
    token = Column(String(64), unique=True, index=True, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    survey = relationship("Survey", back_populates="links")

class Respondent(Base):
    __tablename__ = "respondents"
    id = Column(Integer, primary_key=True, index=True)
    link_id = Column(Integer, ForeignKey("survey_links.id", ondelete="SET NULL"))
    display_name = Column(String(255), nullable=True)
    status = Column(String(20), default="in_progress")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    answers = relationship("Answer", back_populates="respondent", cascade="all, delete-orphan")

class Answer(Base):
    __tablename__ = "answers"
    id = Column(Integer, primary_key=True, index=True)
    respondent_id = Column(Integer, ForeignKey("respondents.id", ondelete="CASCADE"), index=True, nullable=False)
    question_id = Column(Integer, ForeignKey("questions.id", ondelete="CASCADE"), index=True, nullable=False)
    answer_text = Column(Text, nullable=True)
    flagged = Column(Boolean, default=False)
    score = Column(Float, nullable=True)
    rationale = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    low_quality = Column(Boolean, default=False)
    respondent = relationship("Respondent", back_populates="answers")
    question = relationship("Question", back_populates="answers")
    referenced_question_ids = Column(Text, nullable=True)
    reference_warning = Column(Text, nullable=True)
