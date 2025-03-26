import click
from rich import print as rprint
from rich.console import Console
from rich.table import Table
from ax_devil_rtsp import __version__

console = Console()

@click.group()
def cli():
    """Axis Devil RTSP - Command line interface for Axis camera RTSP streams."""
    pass

@cli.command()
def version():
    """Show version information."""
    rprint(f"[bold green]ax-devil-rtsp[/] version {__version__}")

@cli.command()
@click.option('--url', envvar='AX_DEVIL_TARGET_URL', help='RTSP URL')
@click.option('--latency', default=100, help='Stream latency in ms')
def metadata(url, latency):
    """Start metadata streaming from camera."""
    from ax_devil_rtsp.metadata_gstreamer import AxisMetadataClient
    client = AxisMetadataClient(url, latency=latency)
    client.start()

@cli.command()
@click.option('--url', envvar='AX_DEVIL_TARGET_URL', help='RTSP URL')
@click.option('--latency', default=100, help='Stream latency in ms')
def video(url, latency):
    """Start video streaming from camera."""
    from ax_devil_rtsp.video_gstreamer import VideoGStreamerClient
    client = VideoGStreamerClient(url, latency=latency)
    client.start()

@cli.command()
def info():
    """Show information about supported features."""
    table = Table(title="Supported Features")
    table.add_column("Feature", style="cyan")
    table.add_column("Description", style="green")
    
    table.add_row("Metadata Streaming", "GStreamer-based RTSP metadata client")
    table.add_row("Video Streaming", "GStreamer-based RTSP video client")
    table.add_row("ONVIF Support", "ONVIF metadata format parsing")
    
    console.print(table)

if __name__ == '__main__':
    cli()
