"""Schemas del perfil del cliente y contexto del gestor."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ClientProfile(BaseModel):
    """Perfil del cliente para el Asesor IA.

    Los campos de identidad (nombre, dni) son opcionales, viajan en memoria
    solo durante la peticion y no se persisten en disco ni en logs.
    """

    # Identidad opcional (no persistir)
    nombre: Optional[str] = None
    dni: Optional[str] = None

    # Demografia
    edad: int = Field(default=45, ge=18, le=99)
    pais: str = "Espana"
    renta: Optional[str] = None

    # Capacidad
    capital: int = Field(default=50000, ge=0)
    aportacion_mensual: int = Field(default=0, ge=0)
    horizonte: str = "5-10 años"

    # Riesgo
    perfil_riesgo: str = "Moderado"

    # Preferencias
    sectores: List[str] = Field(default_factory=list)
    regiones: List[str] = Field(default_factory=list)
    excluir: List[str] = Field(default_factory=list)
    notas: Optional[str] = None

    # Contexto del gestor (puede venir aqui o como query param)
    gestora_propia: Optional[str] = None

    def to_dict(self) -> dict:
        return self.model_dump(exclude_none=False)
