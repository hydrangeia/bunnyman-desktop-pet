import pytest

from snap_geometry import Anchor, Rect, Surface, find_snap, find_support, position_for_anchor


SPRITE=Rect(200,100,340,300)
SCREEN=Surface('screen:main',Rect(0,0,1920,1040),'screen')
WINDOW=Surface('window:1',Rect(300,400,1000,800))


def test_sprite_feet_attach_to_window_top_not_canvas_edge():
    result=find_snap((100,82),SPRITE,[WINDOW])
    assert result is not None
    pos,anchor=result
    assert anchor.side=='top'
    assert pos[1]+SPRITE.bottom==WINDOW.rect.top
    assert pos[1]!=WINDOW.rect.top


@pytest.mark.parametrize('side',['top','bottom','left','right'])
def test_screen_docking_keeps_whole_visible_body_inside_work_area(side):
    pos=position_for_anchor(Anchor(SCREEN.id,side,0),SCREEN,SPRITE)
    box=SPRITE.translated(*pos)
    assert box.left>=0 and box.top>=0
    assert box.right<=1920 and box.bottom<=1040


def test_screen_floor_uses_work_area_above_taskbar():
    pos,anchor=find_snap((600,730),SPRITE,[SCREEN])
    assert anchor.side=='bottom'
    assert pos[1]+SPRITE.bottom==1040


def test_moved_and_resized_window_preserves_relative_perch():
    anchor=Anchor(WINDOW.id,'top',0.25)
    before=position_for_anchor(anchor,WINDOW,SPRITE)
    moved=Surface(WINDOW.id,Rect(400,450,1100,850))
    after=position_for_anchor(anchor,moved,SPRITE)
    assert after==(before[0]+100,before[1]+50)
    resized=Surface(WINDOW.id,Rect(300,400,1300,800))
    after_resize=position_for_anchor(anchor,resized,SPRITE)
    assert after_resize[0]+SPRITE.center_x==550


def test_sleeping_lower_body_still_touches_support():
    anchor=Anchor(WINDOW.id,'top',0.5)
    sleeping=Rect(190,190,420,330)
    awake=position_for_anchor(anchor,WINDOW,SPRITE)
    asleep=position_for_anchor(anchor,WINDOW,sleeping)
    assert awake[1]+SPRITE.bottom==asleep[1]+sleeping.bottom==400
    assert asleep[1]==awake[1]-30


def test_support_chooses_nearest_window_below_not_window_above():
    above=Surface('above',Rect(300,100,1000,350))
    below=Surface('below',Rect(300,600,1000,800))
    result=find_support((200,100),SPRITE,[above,below,SCREEN])
    assert result is not None
    pos,anchor=result
    assert anchor.surface_id=='below'
    assert pos[1]+SPRITE.bottom==600


def test_closed_window_falls_back_to_screen_support():
    pos,anchor=find_support((200,100),SPRITE,[SCREEN])
    assert anchor.surface_id==SCREEN.id
    assert pos[1]+SPRITE.bottom==1040


def test_snap_requires_nearby_edge_and_orthogonal_overlap():
    assert find_snap((100,0),SPRITE,[WINDOW],threshold=24) is None
    assert find_snap((-500,100),SPRITE,[WINDOW],threshold=24) is None


def test_foremost_window_wins_an_equal_edge():
    front=Surface('front',WINDOW.rect)
    _,anchor=find_snap((100,100),SPRITE,[front,WINDOW])
    assert anchor.surface_id=='front'


def test_negative_monitor_coordinates_are_supported():
    left=Surface('screen:left',Rect(-1920,0,0,1040),'screen')
    pos,anchor=find_snap((-2110,500),SPRITE,[left])
    assert anchor.side=='left'
    assert pos[0]+SPRITE.left==-1920


def test_window_bottom_is_outside_and_screen_bottom_is_inside():
    window_pos=position_for_anchor(Anchor(WINDOW.id,'bottom',0.5),WINDOW,SPRITE)
    screen_pos=position_for_anchor(Anchor(SCREEN.id,'bottom',0.5),SCREEN,SPRITE)
    assert window_pos[1]+SPRITE.top==800
    assert screen_pos[1]+SPRITE.bottom==1040
