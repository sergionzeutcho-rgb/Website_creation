"""
Script to update time slots to 30-minute intervals over 24 hours.
This will add all missing time slots (48 total) while keeping existing ones.
"""
import os
import sys
from app import app, db
from models import AvailableTimeSlot

def update_time_slots():
    with app.app_context():
        print("Updating time slots to 30-minute intervals over 24 hours...")
        
        # Get all existing slots
        existing_slots = {slot.time_slot for slot in AvailableTimeSlot.query.all()}
        print(f"Found {len(existing_slots)} existing time slots")
        
        # Generate all 48 slots (24 hours * 2 = 30min intervals)
        added_count = 0
        for hour in range(24):
            for minute in [0, 30]:
                time_str = f"{hour:02d}:{minute:02d}"
                
                if time_str not in existing_slots:
                    order = hour * 2 + (1 if minute == 30 else 0)
                    # Default: activate slots between 08:00-20:00, deactivate others
                    is_active = (8 <= hour < 20)
                    slot = AvailableTimeSlot(time_slot=time_str, order=order, is_active=is_active)
                    db.session.add(slot)
                    added_count += 1
                    print(f"  Added: {time_str} (active: {is_active})")
        
        if added_count > 0:
            db.session.commit()
            print(f"\n✓ Successfully added {added_count} new time slots")
        else:
            print("\n✓ All time slots already exist")
        
        # Display summary
        total_slots = AvailableTimeSlot.query.count()
        active_slots = AvailableTimeSlot.query.filter_by(is_active=True).count()
        print(f"\nTotal time slots: {total_slots}")
        print(f"Active time slots: {active_slots}")
        print(f"Inactive time slots: {total_slots - active_slots}")
        
        print("\n✓ You can now manage all time slots in Admin → Availability")

if __name__ == '__main__':
    update_time_slots()
