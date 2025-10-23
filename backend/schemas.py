# schemas.py
from pydantic import BaseModel, Field
from typing import List, Optional, Literal

class QuestionCreate(BaseModel):
    text: str
    order_index: int = 0
    type: str = "text"

class SurveyCreate(BaseModel):
    title: str
    description: Optional[str] = None
    questions: List[QuestionCreate] = []  
    guideline: Optional[str] = None       # legacy field 

class SurveyOut(BaseModel):
    id: int
    title: str
    description: Optional[str]
    class Config:
        from_attributes = True

class GuidelineOut(BaseModel):
    content: str

class QuestionOut(BaseModel):
    id: int
    order_index: int
    text: str
    type: str
    guideline: Optional[GuidelineOut] = None
    class Config:
        from_attributes = True

class SurveyDetail(BaseModel):
    survey: SurveyOut
    questions: List[QuestionOut]

class LinkCreate(BaseModel):
    survey_id: int
    expires_in_days: int | None = None   
    scope: Literal["submit","read"] | None = None 

class RespondentCreate(BaseModel):
    link_token: str
    display_name: Optional[str] = None

class AnswerCreate(BaseModel):
    respondent_id: int
    question_id: int
    answer_text: Optional[str] = None
    flagged: bool = False

class AnswerUpdate(BaseModel):
    answer_text: Optional[str] = None
    flagged: Optional[bool] = None

class SubmitSurvey(BaseModel):
    respondent_id: int

class AdminAuth(BaseModel):
    api_key: str = Field(..., description="Admin API key from server .env")

class QuestionGuidelineUpsert(BaseModel):
    content: str
