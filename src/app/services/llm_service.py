from llama_index.core import VectorStoreIndex, Document, Settings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding 
from llama_index.llms.openai import OpenAI
from llama_index.llms.groq import Groq  
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings

class LLMCampaignService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = None
        self.embed_model = None
        self.index = None
        self.initialize_llm()
    
    def initialize_llm(self):
        """Initialize LLM and embedding model"""
        try:
            provider = settings.LLM_PROVIDER.lower()
            model_name = settings.LLM_MODEL

            if provider == "openai":
                import os
                os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
                self.llm = OpenAI(model=model_name)

            elif provider == "groq":
                import os
                os.environ["GROQ_API_KEY"] = settings.GROQ_API_KEY
                self.llm = Groq(model=model_name)

            else:
                raise ValueError(f"Unsupported LLM provider: {provider}")

            # Embedding model - FIXED: Added proper import
            self.embed_model = HuggingFaceEmbedding(
                model_name="sentence-transformers/all-mpnet-base-v2"
            )

            Settings.llm = self.llm
            Settings.embed_model = self.embed_model
            print(f"LLM initialized: {provider} ({model_name})")

        except Exception as e:
            print(f"LLM initialization failed: {e}")