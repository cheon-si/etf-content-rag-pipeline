import logging

from app.pipeline.run_pipeline import run_pipeline


def main() -> None:
    """Application entrypoint."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logger = logging.getLogger(__name__)

    logger.info("Application started.")
    try:
        rows = run_pipeline()
        logger.info("Application finished successfully (rows=%d).", len(rows))
    except Exception:
        logger.exception("Application failed during pipeline execution.")
        raise


if __name__ == "__main__":
    main()
