import asyncio
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema.runnable import RunnablePassthrough
import os
import psycopg2
from psycopg2.extras import DictCursor
import hashlib
from chromadb.config import Settings
import chromadb
from langchain.docstore.document import Document
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class EmailAnalyzer:
    def __init__(self):
        self.embeddings = OpenAIEmbeddings()
        self.chroma_client = None
        self.collection = None
        self.llm = ChatOpenAI(model="gpt-4o-mini")
        
        # Database configuration
        self.db_config = {
            'host': os.getenv('DB_HOST', 'db'),
            'port': int(os.getenv('DB_PORT', 5432)),
            'database': os.getenv('DB_NAME', 'emails'),
            'user': os.getenv('DB_USER', 'postgres'),
            'password': os.getenv('DB_PASSWORD', 'postgres')
        }
        
        # ChromaDB configuration
        self.chroma_host = os.getenv('CHROMA_HOST', 'chroma')
        self.chroma_port = os.getenv('CHROMA_PORT', '8000')
    
    def get_db_connection(self):
        """Établit une connexion à la base de données PostgreSQL"""
        return psycopg2.connect(**self.db_config)

    def get_db_hash(self):
        """Calcule un hash de la base de données emails"""
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT MAX(date), COUNT(*) FROM emails")
                    result = cursor.fetchone()
                    return hashlib.md5(f"{result[0]}_{result[1]}".encode()).hexdigest()
        except Exception as e:
            logger.error(f"Error calculating DB hash: {e}")
            raise

    def prepare_email_documents(self):
        """Prépare les documents à partir des emails en base de données"""
        try:
            with self.get_db_connection() as conn:
                with conn.cursor(cursor_factory=DictCursor) as cursor:
                    cursor.execute("""
                        SELECT sender, subject, date, body, unique_id 
                        FROM emails 
                        ORDER BY date DESC
                    """)
                    
                    documents = []
                    metadatas = []
                    ids = []
                    texts = []
                    
                    for email in cursor:
                        content = f"""
                        De: {email['sender']}
                        Objet: {email['subject']}
                        Date: {email['date']}
                        
                        {email['body']}
                        """
                        
                        documents.append(Document(
                            page_content=content,
                            metadata={
                                "sender": email['sender'],
                                "subject": email['subject'],
                                "date": str(email['date']),
                                "email_id": email['unique_id']
                            }
                        ))
                        
                        texts.append(content)
                        metadatas.append({
                            "sender": email['sender'],
                            "subject": email['subject'],
                            "date": str(email['date']),
                            "email_id": email['unique_id']
                        })
                        ids.append(email['unique_id'])
                    
                    return documents, texts, metadatas, ids
        except Exception as e:
            logger.error(f"Error preparing email documents: {e}")
            raise

    async def setup_vector_store(self, force_refresh: bool = False):
        """Initialise ou charge la base de données vectorielle"""
        try:
            # Connexion au serveur ChromaDB
            self.chroma_client = chromadb.HttpClient(
                host=self.chroma_host,
                port=self.chroma_port,
                settings=Settings(anonymized_telemetry=False)
            )
            
            collection_name = "email_collection"
            
            # Supprime la collection si force_refresh est True
            if force_refresh and collection_name in [col.name for col in self.chroma_client.list_collections()]:
                self.chroma_client.delete_collection(collection_name)
            
            # Crée ou récupère la collection
            self.collection = self.chroma_client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"}
            )
            
            # Vérifie si une mise à jour est nécessaire
            current_hash = self.get_db_hash()
            collection_metadata = self.collection.metadata
            if not force_refresh and collection_metadata and collection_metadata.get('db_hash') == current_hash:
                logger.info("Vector database is up to date")
                return
            
            # Prépare et ajoute les documents
            documents, texts, metadatas, ids = self.prepare_email_documents()
            
            # Ajoute les documents par lots
            batch_size = 100
            for i in range(0, len(texts), batch_size):
                batch_texts = texts[i:i + batch_size]
                batch_metadatas = metadatas[i:i + batch_size]
                batch_ids = ids[i:i + batch_size]
                
                embeddings = self.embeddings.embed_documents(batch_texts)
                
                self.collection.add(
                    embeddings=embeddings,
                    documents=batch_texts,
                    metadatas=batch_metadatas,
                    ids=batch_ids
                )
            
            # Met à jour le hash de la base
            self.collection.modify(metadata={"db_hash": current_hash})
            logger.info("Vector database updated successfully")
            
        except Exception as e:
            logger.error(f"Failed to setup vector store: {e}")
            raise

    async def search_with_context(self, question: str, limit: int = 3, score_threshold: float = 0.5):
        """
        Recherche dans les emails et retourne la réponse AI et les emails pertinents
        
        Args:
            question (str): La question à rechercher
            limit (int): Nombre maximum de résultats à retourner
            score_threshold (float): Score minimum de similarité (entre 0 et 1) pour inclure un résultat
        """
        if not self.collection:
            raise Exception("Vector store not initialized")
        
        try:
            # Obtient l'embedding de la question
            question_embedding = self.embeddings.embed_query(question)
            
            # Recherche les documents pertinents avec scores
            results = self.collection.query(
                query_embeddings=[question_embedding],
                n_results=limit,
                include=["documents", "metadatas", "distances"]
            )
            
            # Convertit les distances en scores de similarité (1 - distance normalisée)
            scores = [1 - min(1, dist) for dist in results['distances'][0]]
            
            # Filtre les résultats selon le score minimum
            filtered_results = []
            filtered_metadata = []
            for doc, metadata, score in zip(results['documents'][0], results['metadatas'][0], scores):
                if score >= score_threshold:
                    filtered_results.append(doc)
                    filtered_metadata.append(metadata)
            
            # Si aucun résultat ne dépasse le seuil
            if not filtered_results:
                return "Aucun email suffisamment pertinent n'a été trouvé pour répondre à cette question.", []
            
            # Prépare les documents filtrés
            documents = []
            for doc, metadata in zip(filtered_results, filtered_metadata):
                documents.append(Document(
                    page_content=doc,
                    metadata=metadata
                ))
            
            context = "\n---\n".join(filtered_results)
            
            # Prépare et exécute la requête
            prompt = ChatPromptTemplate.from_template("""
                En te basant sur le contexte des emails suivants, réponds à cette question :
                "{question}"

                Contexte des emails :
                {context}

                Si la réponse ne peut pas être trouvée dans les emails, dis-le clairement.
                Réponse :
                """)
            
            chain = (
                {
                    "context": RunnablePassthrough(),
                    "question": lambda x: question
                }
                | prompt
                | self.llm
            )
        
            response = await chain.ainvoke(context)
            return response.content, documents
            
        except Exception as e:
            logger.error(f"Error during search: {e}")
            raise