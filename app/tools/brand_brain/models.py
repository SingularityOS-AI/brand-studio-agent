"""
Data models for Brand Brain

Pydantic models for validation and serialization.

CORE INVARIANT: No Section can exist without a non-empty citation_text.
This invariant is enforced at construction time - not optional validation.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Literal
from datetime import datetime
import json


class CitationInvariantError(ValueError):
    """Raised when Section violates citation invariant (required for product integrity)."""
    pass


@dataclass
class Section:
    """
    A single brand brain section.

    CORE INVARIANT: citation_text MUST be non-empty and not all whitespace.
    citation_source MUST be 'usuario' or 'analisis_publico'.
    
    This invariant is ENFORCED AT CONSTRUCTION - not optional validation.
    If you try to create a Section with empty citation_text, it raises ValueError.
    """
    id: str
    label: str
    status: Literal["propuesto", "confirmado"]  # "propuesto" = agent proposed, "confirmado" = user agreed
    content: Dict  # Section-specific data (journey stages, pain point, etc.)
    citation_text: str  # Quote from user or analysis - MUST be non-empty
    citation_source: Literal["usuario", "analisis_publico"]
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def __post_init__(self):
        """
        Enforce core invariant at construction time.
        
        Raises:
            CitationInvariantError: If citation_text is empty/whitespace or citation_source is invalid
        """
        # Check citation_text - must be non-empty after stripping whitespace
        if not self.citation_text or not self.citation_text.strip():
            raise CitationInvariantError(
                f"Section '{self.id}' ({self.label}): citation_text cannot be empty or whitespace"
            )
        
        # Validate citation_source
        if self.citation_source not in ["usuario", "analisis_publico"]:
            raise CitationInvariantError(
                f"Section '{self.id}' ({self.label}): citation_source must be 'usuario' or 'analisis_publico', got '{self.citation_source}'"
            )

    def validate_invariant(self) -> bool:
        """
        Check if section satisfies citation invariant (for UI/reporting purposes).
        
        Note: This is primarily for reporting - the invariant is already enforced
        at construction time. If a Section exists, it SHOULD always pass this check.
        
        Returns:
            bool: True if section is valid (should always be True for constructed objects)
        """
        try:
            # Re-run the checks (should never fail for properly constructed objects)
            if not self.citation_text or not self.citation_text.strip():
                return False
            if self.citation_source not in ["usuario", "analisis_publico"]:
                return False
            return True
        except Exception:
            return False


@dataclass
class BrandBrain:
    """
    Complete brand brain with all nine sections.

    Sections are stored in order for display purposes.
    """
    sections: List[Section] = field(default_factory=list)
    formato: Optional[str] = None  # Optional: "video", "workshop", etc.
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def get_section(self, section_id: str) -> Optional[Section]:
        """Get a section by ID"""
        for section in self.sections:
            if section.id == section_id:
                return section
        return None

    def upsert_section(
        self,
        section_id: str,
        label: str,
        content: Dict,
        citation_text: str,
        citation_source: Literal["usuario", "analisis_publico"],
        status: Literal["propuesto", "confirmado"] = "propuesto"
    ) -> Section:
        """
        Update or insert a section.
        
        Note: This method creates a new Section object, which will enforce the citation
        invariant at construction. If you try to update with empty citation_text, it will
        raise CitationInvariantError.
        """
        existing = self.get_section(section_id)

        if existing:
            # Update existing - create new object to enforce invariant
            # This is intentional: even updates must pass validation
            new_section = Section(
                id=section_id,
                label=label,
                content=content,
                citation_text=citation_text,
                citation_source=citation_source,
                status=status
            )
            new_section.created_at = existing.created_at
            new_section.updated_at = datetime.utcnow().isoformat()
            
            # Replace in list
            idx = self.sections.index(existing)
            self.sections[idx] = new_section
            self.updated_at = datetime.utcnow().isoformat()
            return new_section
        else:
            # Insert new - will enforce invariant in __post_init__
            new_section = Section(
                id=section_id,
                label=label,
                content=content,
                citation_text=citation_text,
                citation_source=citation_source,
                status=status
            )
            self.sections.append(new_section)
            self.updated_at = datetime.utcnow().isoformat()
            return new_section

    def validate_all_sections(self) -> Dict[str, bool]:
        """
        Validate all sections enforce the citation invariant.

        Returns: Dict mapping section_id -> is_valid
        """
        return {section.id: section.validate_invariant() for section in self.sections}

    def all_sections_valid(self) -> bool:
        """
        Check if all sections pass validation.
        
        Note: Since Sections enforce the invariant at construction, this should
        always return True if the brain was properly constructed. This method exists
        for data validation when loading from external sources (e.g., database).
        """
        return all(section.validate_invariant() for section in self.sections)

    def get_section_order(self) -> List[str]:
        """Return section IDs in canonical order"""
        from app.tools.brand_brain.questions import get_section_order
        canonical_order = get_section_order()
        # Filter to sections we have
        return [sid for sid in canonical_order if self.get_section(sid)]

    def to_dict(self) -> Dict:
        """Serialize to dict for storage"""
        return {
            "sections": [
                {
                    "id": s.id,
                    "label": s.label,
                    "status": s.status,
                    "content": s.content,
                    "citation_text": s.citation_text,
                    "citation_source": s.citation_source,
                    "created_at": s.created_at,
                    "updated_at": s.updated_at
                }
                for s in self.sections
            ],
            "formato": self.formato,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "BrandBrain":
        """
        Deserialize from dict from storage.
        
        WARNING: This bypasses normal construction validation - use validate_invariant()
        to ensure data integrity when loading from external sources.
        """
        sections = []
        for s_data in data.get("sections", []):
            section = Section(
                id=s_data["id"],
                label=s_data["label"],
                status=s_data["status"],
                content=s_data["content"],
                citation_text=s_data["citation_text"],
                citation_source=s_data["citation_source"]
            )
            if "created_at" in s_data:
                section.created_at = s_data["created_at"]
            if "updated_at" in s_data:
                section.updated_at = s_data["updated_at"]
            sections.append(section)

        brain = cls(
            sections=sections,
            formato=data.get("formato")
        )
        if "created_at" in data:
            brain.created_at = data["created_at"]
        if "updated_at" in data:
            brain.updated_at = data["updated_at"]

        return brain
