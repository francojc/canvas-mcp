"""Course-related MCP tools for Canvas API."""

from typing import Union
from mcp.server.fastmcp import FastMCP

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.client import fetch_all_paginated_results, make_canvas_request
from core.cache import get_course_id, get_course_code, course_code_to_id_cache, id_to_course_code_cache
from core.validation import validate_params
from core.dates import format_date


def register_course_tools(mcp: FastMCP):
    """Register all course-related MCP tools."""
    
    @mcp.tool()
    async def list_courses(include_concluded: bool = False, include_all: bool = False) -> str:
        """List courses for the authenticated user."""
        
        params = {
            "include[]": ["term", "teachers", "total_students"],
            "per_page": 100
        }
        
        if not include_all:
            params["enrollment_type"] = "teacher"
        
        if include_concluded:
            params["state[]"] = ["available", "completed"]
        else:
            params["state[]"] = ["available"]
        
        courses = await fetch_all_paginated_results("/courses", params)
        
        if isinstance(courses, dict) and "error" in courses:
            return f"Error fetching courses: {courses['error']}"
        
        if not courses:
            return "No courses found."
        
        # Refresh our caches with the course data
        for course in courses:
            course_id = str(course.get("id"))
            course_code = course.get("course_code")
            
            if course_code and course_id:
                course_code_to_id_cache[course_code] = course_id
                id_to_course_code_cache[course_id] = course_code
        
        courses_info = []
        for course in courses:
            course_id = course.get("id")
            name = course.get("name", "Unnamed course")
            code = course.get("course_code", "No code")
            
            # Emphasize code in the output
            courses_info.append(f"Code: {code}\nName: {name}\nID: {course_id}\n")
        
        return "Courses:\n\n" + "\n".join(courses_info)

    @mcp.tool()
    @validate_params
    async def get_course_details(course_identifier: Union[str, int]) -> str:
        """Get detailed information about a specific course.
        
        Args:
            course_identifier: The Canvas course code (e.g., badm_554_120251_246794) or ID
        """
        course_id = await get_course_id(course_identifier)
        
        response = await make_canvas_request("get", f"/courses/{course_id}")
        
        if "error" in response:
            return f"Error fetching course details: {response['error']}"
        
        # Update our caches with the course data
        if "id" in response and "course_code" in response:
            course_code_to_id_cache[response["course_code"]] = str(response["id"])
            id_to_course_code_cache[str(response["id"])] = response["course_code"]
        
        details = [
            f"Code: {response.get('course_code', 'N/A')}",
            f"Name: {response.get('name', 'N/A')}",
            f"Start Date: {format_date(response.get('start_at'))}",
            f"End Date: {format_date(response.get('end_at'))}",
            f"Time Zone: {response.get('time_zone', 'N/A')}",
            f"Default View: {response.get('default_view', 'N/A')}",
            f"Public: {response.get('is_public', False)}",
            f"Blueprint: {response.get('blueprint', False)}"
        ]
        
        # Prefer to show course code in the output
        course_display = response.get("course_code", course_identifier)
        return f"Course Details for {course_display}:\n\n" + "\n".join(details)

    @mcp.tool()
    @validate_params
    async def get_course_content_overview(course_identifier: Union[str, int], 
                                        include_pages: bool = True,
                                        include_modules: bool = True) -> str:
        """Get a comprehensive overview of course content including pages and modules.
        
        Args:
            course_identifier: The Canvas course code (e.g., badm_554_120251_246794) or ID
            include_pages: Whether to include pages information
            include_modules: Whether to include modules and their items
        """
        course_id = await get_course_id(course_identifier)
        
        overview_sections = []
        
        # Get course details for context
        course_response = await make_canvas_request("get", f"/courses/{course_id}")
        if "error" not in course_response:
            course_name = course_response.get("name", "Unknown Course")
            overview_sections.append(f"Course: {course_name}")
        
        # Get pages if requested
        if include_pages:
            pages = await fetch_all_paginated_results(f"/courses/{course_id}/pages", {"per_page": 100})
            if isinstance(pages, list):
                published_pages = [p for p in pages if p.get("published", False)]
                unpublished_pages = [p for p in pages if not p.get("published", False)]
                front_pages = [p for p in pages if p.get("front_page", False)]
                
                pages_summary = [
                    f"\nPages Summary:",
                    f"  Total Pages: {len(pages)}",
                    f"  Published: {len(published_pages)}",
                    f"  Unpublished: {len(unpublished_pages)}",
                    f"  Front Pages: {len(front_pages)}"
                ]
                
                if published_pages:
                    pages_summary.append(f"\nRecent Published Pages:")
                    # Sort by updated_at and show first 5
                    sorted_pages = sorted(published_pages, 
                                        key=lambda x: x.get("updated_at", ""), 
                                        reverse=True)
                    for page in sorted_pages[:5]:
                        title = page.get("title", "Untitled")
                        updated = format_date(page.get("updated_at"))
                        pages_summary.append(f"    {title} (Updated: {updated})")
                
                overview_sections.append("\n".join(pages_summary))
        
        # Get modules if requested
        if include_modules:
            modules = await fetch_all_paginated_results(f"/courses/{course_id}/modules", {"per_page": 100})
            if isinstance(modules, list):
                modules_summary = [
                    f"\nModules Summary:",
                    f"  Total Modules: {len(modules)}"
                ]
                
                # Count module items by type across all modules
                item_type_counts = {}
                total_items = 0
                
                for module in modules[:10]:  # Limit to first 10 modules to avoid too many API calls
                    module_id = module.get("id")
                    if module_id:
                        items = await fetch_all_paginated_results(
                            f"/courses/{course_id}/modules/{module_id}/items", 
                            {"per_page": 100}
                        )
                        if isinstance(items, list):
                            total_items += len(items)
                            for item in items:
                                item_type = item.get("type", "Unknown")
                                item_type_counts[item_type] = item_type_counts.get(item_type, 0) + 1
                
                modules_summary.append(f"  Total Items Analyzed: {total_items}")
                if item_type_counts:
                    modules_summary.append(f"  Item Types:")
                    for item_type, count in sorted(item_type_counts.items()):
                        modules_summary.append(f"    {item_type}: {count}")
                
                # Show module structure for first few modules
                if modules:
                    modules_summary.append(f"\nModule Structure (first 3):")
                    for module in modules[:3]:
                        name = module.get("name", "Unnamed")
                        state = module.get("state", "unknown")
                        modules_summary.append(f"    {name} (Status: {state})")
                
                overview_sections.append("\n".join(modules_summary))
        
        # Try to get the course code for display
        course_display = await get_course_code(course_id) or course_identifier
        result = f"Content Overview for Course {course_display}:" + "\n".join(overview_sections)
        
        return result