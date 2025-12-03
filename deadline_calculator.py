from datetime import datetime, timezone

class DeadlineCalculator:
    """
    Single Responsibility: Calculate remaining time and urgency levels.
    Uses strict DD:HH:MM:SS format for visual consistency.
    """

    def process_requests(self, requests_list):
        processed = []
        now = datetime.now(timezone.utc)

        for req in requests_list:
            item = req.copy()
            item['reply_status'] = self.calculate_time_left(item.get('reply_limit'), now)
            item['resolve_status'] = self.calculate_time_left(item.get('resolve_limit'), now)
            processed.append(item)
        return processed

    def calculate_time_left(self, limit_input, now_dt):
        """
        Returns status, color, and text in DD:HH:MM:SS format.
        Overdue items show negative time (e.g., -01d 02:00:00).
        """
        if not limit_input:
            return {"text": "--:--:--:--", "color": "grey", "seconds_left": 999999, "limit_date": None}

        try:
            # 1. Normalize input to datetime
            if isinstance(limit_input, str):
                limit_dt = datetime.fromisoformat(limit_input.replace('Z', '+00:00'))
            else:
                limit_dt = limit_input

            # 2. Calculate difference
            diff = limit_dt - now_dt
            total_seconds = int(diff.total_seconds())
            
            # 3. Calculate components (absolute values for formatting)
            abs_seconds = abs(total_seconds)
            days = abs_seconds // 86400
            rem_seconds = abs_seconds % 86400
            hours = rem_seconds // 3600
            rem_seconds %= 3600
            minutes = rem_seconds // 60
            seconds = rem_seconds % 60

            # 4. Format Logic (Digital Clock Style)
            # Format: DDd HH:MM:SS (e.g. 01d 12:30:45)
            time_str = f"{days:02}d {hours:02}:{minutes:02}:{seconds:02}"

            if total_seconds < 0:
                # OVERDUE CASE: Red color and negative sign
                color = "red"
                text = f"-{time_str}" # Result: -00d 01:30:00
            
            else:
                # ACTIVE CASE
                text = time_str
                
                # Color logic based on urgency
                if total_seconds < 7200: # Less than 2 hours
                    color = "orange" # Urgent
                elif total_seconds < 14400: # Less than 4 hours
                    color = "yellow" # Warning
                else:
                    color = "green" # Good

            return {
                "text": text,
                "color": color,
                "seconds_left": total_seconds,
                "limit_date": limit_dt
            }

        except Exception as e:
            return {"text": "Date Error", "color": "grey", "limit_date": None}